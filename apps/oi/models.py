# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.conf import settings
from django.db import models
from django.db.models import F
from django.db.models.fields import Field, related, FieldDoesNotExist
from django.contrib.auth.models import User
from django.contrib.contenttypes import models as content_models
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes import fields as generic_fields
from django.core.validators import RegexValidator

from imagekit.models import ImageSpecField
from imagekit.processors import ResizeToFit
from taggit.managers import TaggableManager

from apps.oi import states, relpath
from apps.oi.helpers import (
    update_count, remove_leading_article, set_series_first_last,
    validated_isbn, get_keywords, save_keywords, on_sale_date_as_string,
    on_sale_date_fields)

# We should just from apps.gcd import models as gcd_models, but that's
# a lot of little changes so for now tell flake8 noqa so it doesn't complain
from apps.gcd.models import *  # noqa
from apps.gcd.models.issue import INDEXED


# TODO: CTYPES and ACTION_* are going away at some point.
CTYPES = {
    'publisher': 1,
    'issue_add': 5,
    'issue_bulk': 8,
    'series': 4,
    'variant_add': 9,
    'two_issues': 10,
}


ACTION_ADD = 'add'
ACTION_DELETE = 'delete'
ACTION_MODIFY = 'modify'


class Changeset(models.Model):

    state = models.IntegerField(db_index=True)

    indexer = models.ForeignKey('auth.User', db_index=True,
                                related_name='changesets')
    along_with = models.ManyToManyField(User,
                                        related_name='changesets_assisting')
    on_behalf_of = models.ManyToManyField(User,
                                          related_name='changesets_source')

    # Changesets don't get an approver until late in the workflow,
    # and for legacy cases we don't know who they were.
    approver = models.ForeignKey('auth.User',  db_index=True,
                                 related_name='approved_%(class)s', null=True)

    # In production, change_type is a tinyint(2) due to the small value set.
    change_type = models.IntegerField(db_index=True)
    migrated = models.BooleanField(default=False, db_index=True)
    date_inferred = models.BooleanField(default=False)

    imps = models.IntegerField(default=0)

    created = models.DateTimeField(auto_now_add=True, db_index=True)
    modified = models.DateTimeField(auto_now=True, db_index=True)

    # TODO: This is just here so we can mock it in unit tests of old code.
    #       It will go away along with CTYPES.
    def changeset_action(self):
        raise NotImplementedError


class ChangesetComment(models.Model):
    """
    Comment class for revision management.

    We are not using Django's comments contrib package for several reasons:

    1.  Additional fields- we want to associate comments with state
        transitions, which also tells us who made the comment (since
        currently comments can only be made by the person changing the
        revision state, or by the indexer when saving intermediate edits.

        TODO: The whole bit where the indexer can end up tacking on a bunch
        of comments rather than having just one that they build up and edit
        and send in with the submission is not quite right.  Needs work still.

    2.  We don't need the anti-spam measures as these will not be accessible
        by the general public.  If we get a spammer with an account we'll have
        bigger problems than comments, and other ways to deal with them.

    3.  Unneeded fields.  This isn't really an obstacle to use, but the
        django comments system copies over a number of fields that we would
        not want copied in case they change (email, for instance).
    """
    class Meta:
        db_table = 'oi_changeset_comment'
        ordering = ['created']

    commenter = models.ForeignKey(User)
    text = models.TextField()

    changeset = models.ForeignKey(Changeset, related_name='comments')

    content_type = models.ForeignKey(content_models.ContentType, null=True)
    revision_id = models.IntegerField(db_index=True, null=True)
    revision = generic_fields.GenericForeignKey('content_type', 'revision_id')

    old_state = models.IntegerField()
    new_state = models.IntegerField()
    created = models.DateTimeField(auto_now_add=True, editable=False)


class RevisionLock(models.Model):
    """
    Indicates that a particular Changeset has a particular row locked.

    In order to have an active Revision for a given row, a Changeset
    must hold a lock on it.  Rows in this table represent locks,
    and the unique_together constraint on the content type and object id
    ensure that only one Changeset can hold an object's lock at a time.
    Locks are released by deleting the row.

    A lock with a NULL changeset is used to check that the object can
    be locked before creating a Changeset that would not be used
    if the lock fails.

    TODO: cron job to periodically scan for stale locks?
    """
    class Meta:
        db_table = 'oi_revision_lock'
        unique_together = ('content_type', 'object_id')

    changeset = models.ForeignKey(Changeset, null=True,
                                  related_name='revision_locks')

    content_type = models.ForeignKey(content_models.ContentType)
    object_id = models.IntegerField(db_index=True)
    locked_object = generic_fields.GenericForeignKey('content_type',
                                                     'object_id')


class RevisionManager(models.Manager):
    """
    Custom manager base class for revisions.
    """
    def active(self):
        """
        For use on the revisions relation from display objects
        where reserved == True.
        Throws the DoesNotExist or MultipleObjectsReturned exceptions on
        the appropriate Revision subclass, as it calls get() underneath.
        """
        return self.get(changeset__state__in=states.ACTIVE)


class Revision(models.Model):
    """
    Abstract base class implementing the workflow of a revisable object.

    This holds the data while it is being edited, and remains in the table
    as a history of each given edit, including those that are discarded.

    A state column tracks the progress of the revision, which should
    eventually end in either the APPROVED or DISCARDED state.

    Various classmethods exist to get information about the revision fields
    so that they can be handled generically.  All of these method names
    start with _get and end with a suffix indicating the return value:

    fields:       a dictionary mapping field attribute names to field objects
    field_names:  a set of field attribute names
    field_tuples: a set of tuples of attribute names that may cross relations
    """
    class Meta:
        abstract = True

    objects = RevisionManager()

    changeset = models.ForeignKey(Changeset, related_name='%(class)ss')
    previous_revision = models.OneToOneField('self', null=True,
                                             related_name='next_revision')

    # If True, this revision deletes the object in question.  Other fields
    # should not contain changes but should instead be a record of the object
    # at the time of deletion and therefore match the previous revision.
    # If changes are present, then they were never actually published and
    # should be ignored in terms of history.
    deleted = models.BooleanField(default=False, db_index=True)

    # If True, this revision has been committed back to the display tables.
    # If False, this revision will never be committed.
    # If None, this revision is still active, and may or may not be committed
    # at some point in the future.
    committed = models.NullBooleanField(default=None, db_index=True)

    comments = generic_fields.GenericRelation(
        ChangesetComment,
        content_type_field='content_type',
        object_id_field='revision_id')

    created = models.DateTimeField(auto_now_add=True, db_index=True)
    modified = models.DateTimeField(auto_now=True, db_index=True)

    is_changed = False

    # These are initialized on first use- see the corresponding classmethods.
    # Set to None as an empty iterable is a valid possible value.
    _regular_fields = None
    _irregular_fields = None
    _single_value_fields = None
    _multi_value_fields = None

    # Child classes must set these properly.  Unlike source, they cannot be
    # instance properties because they are needed during revision construction.
    source_name = NotImplemented
    source_class = NotImplemented

    @property
    def source(self):
        """
        The thing of which this is a revision.
        Since this is different for each revision,
        the subclass must override this.
        """
        raise NotImplementedError

    @source.setter
    def source(self, value):
        """
        Used with source_class by base revision code to create new objects.
        """
        raise NotImplementedError

    @property
    def added(self):
        """
        True if this is an open or committed add.
        """
        return not self.previous_revision and not self.discarded

    @property
    def edited(self):
        """
        True if this open or committed and neither an add nor a delete.

        NOTE: This does not necessarily mean there have been any edits.
        """
        return bool(self.previous_revision and not
                    (self.deleted or self.discarded))

    @property
    def discarded(self):
        """
        For symmetry with committed and open.
        """
        return self.committed is False

    @property
    def open(self):
        """
        For symmetry with committed and discarded.
        """
        return self.committed is None

    # ##################################################################
    # Field declarations and methods for creating revisions.

    @classmethod
    def _classify_fields(cls):
        """
        Populates the regular and irregular field dictionaries.

        This should be called at most once during the life of the class.
        It relies on the excluded field set to filter out irrelevant fields.
        """
        if cls._regular_fields is not None:
            # Already classified.
            return

        # NOTE: As of Django 1.9, reverse relations show up in the list
        #       of fields, but are not actually Field instances.  Since
        #       we don't want them anyway, use this to filter them out.
        #
        #       In a future release of Django this will change, but should
        #       be covered in the release notes.  And presumably there
        #       will be a different reliable way to filter them out.
        excluded = cls._get_excluded_field_names()
        data_fields = {
            f.get_attname(): f
            for f in cls.source_class._meta.get_fields()
            if isinstance(f, Field) and f.get_attname() not in excluded
        }
        rev_fields = {
            f.get_attname(): f
            for f in cls._meta.get_fields()
            if isinstance(f, Field) and f.get_attname() not in excluded
        }
        cls._regular_fields = {}
        cls._irregular_fields = {}
        cls._single_value_fields = {}
        cls._multi_value_fields = {}

        for name, data_field in data_fields.iteritems():
            # Note that ForeignKeys and OneToOneFields show up under the
            # attribute name for the actual key ('parent_id' instead of
            # 'parent'), so strip the _id off for more convenient use.
            # You can still pass the 'parent' form to _meta.get_field().
            # TODO: Is there a more reliable way to do this?  Cannot
            #       seem to find anything in the Django 1.9 API.
            key_name = name
            if ((data_field.many_to_one or data_field.one_to_one) and
                    name.endswith('_id')):
                # If these aren't the same we have no idea what's going
                # on, so an AssertionError is appropriate.
                assert cls.source_class._meta.get_field(key_name) == data_field
                key_name = name[:-len('_id')]

            if name not in rev_fields:
                # No corresponding revision field, so it can't be regular.
                cls._irregular_fields[key_name] = data_field
                continue

            # The internal type is the field type i.e. CharField or ForeignKey.
            rev_field = rev_fields[name]
            rev_ftype = rev_field.get_internal_type()
            data_ftype = data_field.get_internal_type()
            rev_target = (rev_field.target_field.get_attname()
                          if isinstance(rev_field, related.RelatedField)
                          else None)
            data_target = (data_field.target_field.get_attname()
                           if isinstance(data_field, related.RelatedField)
                           else None)

            if rev_ftype == data_ftype and rev_target == data_target:
                # Non-relational fields have a .rel of None.  While we should
                # never have identically named foreign keys that point to
                # different things, it's better to check than assume.
                #
                # Most of these fields can be copied, including ManyToMany
                # fields, although ManyToMany fields may need to be treated
                # differently in other ways, so we track them separately
                # as well.
                cls._regular_fields[key_name] = data_field

                if data_field.many_to_many or data_field.one_to_many:
                    cls._multi_value_fields[key_name] = data_field
                else:
                    cls._single_value_fields[key_name] = data_field

            elif isinstance(data_field,
                            TaggableManager) and name == 'keywords':
                # Keywords are regular but not assignable in the same way
                # as single- or multi-value fields as the keywords are
                # stored as a single string in revisions.
                cls._regular_fields[key_name] = data_field

            else:
                # There's some mismatch, so we don't know how to handle this.
                cls._irregular_fields[key_name] = data_field

    @classmethod
    def _get_excluded_field_names(cls):
        """
        Field names that appear to be regular fields but should be ignored.

        Any data object field that has a matching (name, type, and if
        relevant related type) field on the revision that should *NOT*
        be copied back and forth should be included here.

        It is not necessary to include non-matching fields here, whether
        they affect revision field values or not.

        Fields listed here may or may not be present on any given data object,
        but if they are present they should be omitted from automatic
        classification.

        Subclasses may add to this set, but should never remove fields from it.

        Deprecated fields should NOT be included, as they should continue
        to be copied back and forth until the data is all removed, at
        which point the field should be dropped from the data object.
        """
        # Not all data objects have all of these, but since this
        # is just used in set subtractions, that is safe to do.
        # All of these fields are common to multiple revision types.
        #
        # id, created, and modified are automatic columns
        # tagged_items is the reverse relation for 'keywords'
        # image_resources are handled through their own ImageRevisions
        return frozenset({
            'id',
            'created',
            'modified',
            'deleted',
            'reserved',
            'tagged_items',
            'image_resources',
        })

    @classmethod
    def _get_deprecated_field_names(cls):
        """
        The set of field names that should not be allowed in new objects.

        These fields are still present in both the data object and revision
        tables, and should therefore be copied out of the data objects in
        case old values are still present and need to be preserved until
        they can be migrated.  But new values should not be allowed.
        """
        return frozenset()

    @classmethod
    def _get_regular_fields(cls):
        """
        Data fields that can be predictably transferred to and from revisions.

        For most fields, this just means copying the value.  For a few
        such as keywords, there is a different but standard way of transferring
        the values.  For ManyToManyFields, the add/remove/set/clear methods
        can be used.
        """
        cls._classify_fields()
        return cls._regular_fields

    @classmethod
    def _get_irregular_fields(cls):
        """
        Data object fields that cannot be handled by generic revision code.

        These fields either don't exist on the revision, or they do not
        match types and we do not understand the mismatch as a well-known
        special case (i.e. keywords as CharField vs TaggableManager).
        """
        cls._classify_fields()
        return cls._irregular_fields

    @classmethod
    def _get_single_value_fields(cls):
        """
        The subset of regular fields that have a single value.
        """
        cls._classify_fields()
        return cls._single_value_fields

    @classmethod
    def _get_multi_value_fields(cls):
        """
        The subset of regular fields that have a queryset value.
        """
        cls._classify_fields()
        return cls._multi_value_fields

    @classmethod
    def _get_conditional_field_tuple_mapping(cls):
        """
        A dictionary of field names mapped to their conditions.

        The conditions are stored as a tuple of field names that can
        be applied to an instance to get the value.
        For example, ('series', 'has_isbn') would mean that you
        could get the value by looking at revision.series.has_isbn
        """
        return {}

    @classmethod
    def _get_parent_field_tuples(cls):
        """
        The set of parent-ish objects that this revision may need to update.

        This should include parent chains up to the root data object(s) that
        need updating, for instance an issue should include its publisher
        by way of the series foreign key (as opposed to publishers found
        through other links, which are either duplicate or should be
        ignored.

        Elements of the set are tuples to allow for multiple parent levels.
        ForeignKey, ManyToManyField, and OneToOneField are all valid
        field types for this method.

        Note that if multiple parents along a path require updating, then
        each level of parent must be included.  In the issue example,
        ('series',) and ('series', 'publisher') must both be included.

        This allows for the case where an intermediate object does not
        require updating.
        """
        return frozenset()

    @classmethod
    def _get_major_flag_field_tuples(cls):
        """
        The set of flags that require further processing upon commit.

        These are stored as tuples in the same way as
        _get_parent_field_tuples().
        """
        return frozenset()

    @classmethod
    def _get_stats_category_field_tuples(cls):
        """
        These fields, when present, determine CountStats categories to update.

        This implementation works for any class that does not have to get
        these fields from a parent object.
        """
        stats_tuples = set()
        for name in ('country', 'language'):
            try:
                # We just call get_field to see if it raises, so we
                # ignore the return value.
                cls._meta.get_field(name)
                stats_tuples.add((name,))
            except FieldDoesNotExist:
                pass

        return stats_tuples

    def _pre_initial_save(self):
        """
        Called just before saving to the database to handle unusual fields.

        Note that if there is a source data object, it will already be set.
        """
        pass

    def _post_m2m_add(self):
        """
        Called after initial save to database and m2m population.

        This is for handling unusual fields that require the revision to
        already exist in the database.
        """
        pass

    @classmethod
    def clone(cls, data_object, changeset):
        """
        Given an existing data object, create a new revision based on it.

        This new revision will be where the edits are made.

        Entirely new data objects should be started by simply instantiating
        a new revision of the approparite type directly.
        """
        # We start with all assignable fields, since we want to copy
        # old values even for deprecated fields.
        rev_kwargs = {field: getattr(data_object, field)
                      for field in cls._get_single_value_fields().keys()}

        # Keywords are not assignable but behave the same way whenever
        # they are present, so handle them here.
        if 'keywords' in cls._get_regular_fields():
            rev_kwargs['keywords'] = get_keywords(data_object)

        # Instantiate the revision.  Since we do not know the exact
        # field name for the data_object, set it through the source property.
        revision = cls(changeset=changeset, **rev_kwargs)

        if data_object:
            revision.source = data_object

            # Link to the previous revision for this data object.
            # It is an error not to have a previous revision for
            # a pre-existing data object.
            previous_revision = type(revision).objects.get(
                next_revision=None,
                changeset__state=states.APPROVED,
                **{revision.source_name: data_object})
            revision.previous_revision = previous_revision

        revision._pre_initial_save()
        revision.save()

        # Populate all of the many to many relations that don't use
        # their own separate revision classes.
        for m2m in revision._get_multi_value_fields().keys():
            getattr(revision, m2m).add(*list(getattr(data_object, m2m).all()))
        revision._post_m2m_add()

        return revision

    # ##################################################################
    # Description of changes, and methods for saving to the data object.

    def _check_major_change(self, attrs):
        """
        Fill out the changes structure for a single attribute tuple.
        """
        old, new = self.source, self
        changes = {}

        # The name of the last foreign key is the name used for
        # tracking changes.  Except 'parent' is tracked as 'publisher'
        # for historical reasons.  Eventually we will likely switch
        # the 'parent' database fields to 'publisher'.
        name = 'publisher' if attrs[-1] == 'parent' else attrs[-1]

        old_rp = relpath.RelPath(self.source_class, *attrs)
        new_rp = relpath.RelPath(type(self), *attrs)

        old_value = old_rp.get_value(old, empty=self.added)
        new_value = new_rp.get_value(new, empty=self.deleted)

        changed = '%s changed' % name
        if self.added or self.deleted:
            changes[changed] = True
        elif old_rp.multi_valued:
            # Different QuerySet objects are never equal, even if they
            # express the same queries and have the same evaluation state.
            # So use sets for determining changes.
            changes[changed] = set(old_value) != set(new_value)
        else:
            changes[changed] = old_value != new_value

        if old_rp.boolean_valued:
            # We only care about the direction of change for booleans.
            # At this time, it is sufficient to treat None for a NullBoolean
            # as False.  This can produce a "changed" (False to or from None)
            # in which both "to" and "from" are False.  Strange but OK.
            #
            # Without the bool(), if old_value (for from) or new_value
            # (for to) are None, then the changes would be set to None
            # instead of True or False.
            changes['to %s' % name] = bool((not old_value) and new_value)
            changes['from %s' % name] = bool(old_value and (not new_value))
        else:
            changes['old %s' % name] = old_value
            changes['new %s' % name] = new_value

        return changes

    def _get_major_changes(self):
        """
        Returns a dictionary for deciding what additional actions are needed.

        Major changes are generally ones that require updating statistics
        and/or cached counts in the display tables.  They may also require
        other actions.

        This method bundles up all of the flags and old vs new values
        needed for easy conditionals and easy calls to update_all_counts().
        """
        changes = {}
        for name_tuple in (self._get_parent_field_tuples() |
                           self._get_major_flag_field_tuples() |
                           self._get_stats_category_field_tuples()):
            changes.update(self._check_major_change(name_tuple))

        return changes

    def _adjust_stats(self, changes, old_counts, new_counts):
        """
        Handles universal statistics updating.

        Child classes should call this with super() before proceeding
        to adjust counts stored in their display objects.
        """
        if (old_counts != new_counts or
                changes.get('country changed', False) or
                changes.get('language changed', False)):
            CountStats.objects.update_all_counts(
                old_counts,
                country=changes.get('old country', None),
                language=changes.get('old language', None),
                negate=True)
            CountStats.objects.update_all_counts(
                new_counts,
                country=changes.get('new country', None),
                language=changes.get('new language', None))

        deltas = {
            k: new_counts.get(k, 0) - old_counts.get(k, 0)
            for k in old_counts.viewkeys() | new_counts.viewkeys()
        }

        if any(deltas.values()):
            for parent_tuple in self._get_parent_field_tuples():
                self._adjust_parent_counts(parent_tuple, changes, deltas,
                                           old_counts, new_counts)

            self.source.update_cached_counts(deltas)
            self.source.save()

    def _adjust_parent_counts(self, parent_tuple, changes, deltas,
                              old_counts, new_counts):
        """
        Handles the counts adjustment for a single parent.
        """
        # Always use the last attribute name for the parent name.
        # But switch 'parent' to 'publisher' (historical reasons).
        parent = (
            'publisher' if parent_tuple[-1] == 'parent' else parent_tuple[-1])

        changed = changes['%s changed' % parent]
        old_value = changes['old %s' % parent]
        new_value = changes['new %s' % parent]

        multi = relpath.RelPath(type(self), *parent_tuple).multi_valued
        if changed:
            if old_value:
                if multi:
                    for v in old_value:
                        v.update_cached_counts(old_counts, negate=True)
                        v.save()
                else:
                    old_value.update_cached_counts(old_counts, negate=True)
                    old_value.save()
            if new_value:
                if multi:
                    for v in new_value:
                        v.update_cached_counts(new_counts)
                        v.save()
                else:
                    new_value.update_cached_counts(new_counts)
                    new_value.save()

        elif old_counts != new_counts:
            # Doesn't matter whether we use old or new as they are the same.
            if multi:
                for v in new_value:
                    v.update_cached_counts(deltas)
                    v.save()
            else:
                new_value.update_cached_counts(deltas)
                new_value.save()

    def _pre_commit_check(self):
        """ Runs sanity checks before anything else in commit_to_display. """
        pass

    def _pre_stats_measurement(self, changes):
        """
        Runs before the old stat counts are collected.

        Typically this is used when a dependent revision must be created
        or otherwise handled outside of the stats measurements to avoid
        double-counting.  For instance creating and committing a revision
        to delete a dependent object.
        """
        pass

    def _pre_delete(self, changes):
        """
        Runs just before the data object is deleted in a deletion revision.
        """
        pass

    def _post_create_for_add(self, changes):
        """
        Runs after a new object is created during an add.

        This is where things like adding many-to-many objects can be done.
        """
        pass

    def _post_assign_fields(self, changes):
        """
        Runs once the added or edited display object is set up.

        Fields that can't be copied directly are handled here.
        Not run for deletions.
        """
        pass

    def _pre_save_object(self, changes):
        """
        Runs just before the display object is saved.

        This is where additional processing related to the major changes,
        such as conditional field adjustments, can be done.
        """
        pass

    def _post_save_object(self, changes):
        """
        Runs just after the display object is saved.

        Typically used to handle many-to-many fields.
        """
        pass

    def _post_adjust_stats(self, changes):
        """
        Runs at the very end of commit_to_display().

        Typically this is used when a dependent revision must be created
        or otherwise handled outside of the stats measurements to avoid
        double-counting.  For instance, creating and committing a revision
        to add or update a dependent object.
        """
        pass

    def _copy_fields_to(self, target, changes=None):
        """
        Used to copy fields from a revision to a display object.

        At the time when this is called, the revision may not yet have
        the display object set as self.source (in the case of a newly
        added object), so the target of the copy is given as a parameter.
        """
        # TODO: Make "changes" required once more of the refactor is done.
        if changes is None:
            changes = {}

        c = self._get_conditional_field_tuple_mapping()
        for field in self._get_single_value_fields().keys():
            # If conditional, apply getattr until we produce the flag
            # value and only assign the field if that flag is True.
            if (field not in c or reduce(getattr, c[field], self)):
                setattr(target, field, getattr(self, field))

    def commit_to_display(self, clear_reservation=True):
        """
        Writes the changes from the revision back to the display object.

        Revisions should handle their own dependencies on other revisions.
        """
        self._pre_commit_check()
        changes = self._get_major_changes()

        self._pre_stats_measurement(changes)
        old_stats = {} if self.added else self.source.stat_counts()

        if self.deleted:
            self._pre_delete(changes)
            self.source.delete()
        else:
            if self.added:
                self.source = self.source_class()
                self._post_create_for_add(changes)

            self._copy_fields_to(self.source, changes)
            self._post_assign_fields(changes)

        if clear_reservation:
            self.source.reserved = False

        self._pre_save_object(changes)
        self.source.save()

        if self.added:
            # Reset the source because now it has a database id,
            # which we must save.  Just saving the added source while
            # it is attached does not update the revision with the newly
            # created source id from the database.
            #
            # We do this because it is easier for all other code if it
            # only works with self.source, no matter whether it is
            # an add, edit, or delete.
            self.source = self.source
            self.save()

        # Keywords must be handled post-save for added objects, and
        # are safe to handle here for other types of revisions.
        if 'keywords' in self._get_regular_fields():
            save_keywords(self, self.source)

        for multi in self._get_multi_value_fields():
            old_rp = relpath.RelPath(type(self), multi)
            new_rp = relpath.RelPath(type(self.source), multi)

            new_rp.set_value(self.source, old_rp.get_value(self))

        self._post_save_object(changes)

        new_stats = self.source.stat_counts()
        self._adjust_stats(changes, old_stats, new_stats)
        self._post_adjust_stats(changes)

    def __unicode__(self):
        """
        String representation for debugging purposes only.

        No UI should rely on this representation being suitable for end users.
        """
        # It's possible to add and delete something at the same time,
        # although we don't currently allow it.  In theory one could
        # edit and delete, although we don't even have any way to indicate
        # that currently.
        action = []
        if self.added:
            action.append('adding')
        if self.edited:
            action.append('editing')
        if self.deleted:
            action.append('deleting')

        return '%r %s %s %r (%r) change %r' % (
            self.id,
            ' & '.join(action),
            self.source_class.__name__,
            self.source,
            None if self.source is None else self.source.id,
            None if self.changeset_id is None else self.changeset_id,
        )


class OngoingReservation(models.Model):
    """
    Represents the ongoing revision on all new issues in a series.

    Whenever an issue is added to a series, if there is an ongoing reservation
    for that series the issue is immediately reserved to the ongoing
    reservation holder.
    """
    class Meta:
        db_table = 'oi_ongoing_reservation'

    indexer = models.ForeignKey(User, related_name='ongoing_reservations')
    series = models.OneToOneField(Series, related_name='ongoing_reservation')
    along_with = models.ManyToManyField(User, related_name='ongoing_assisting')
    on_behalf_of = models.ManyToManyField(User, related_name='ongoing_source')

    """
    The creation timestamp for this reservation.
    """
    created = models.DateTimeField(auto_now_add=True, db_index=True)


class LinkRevision(Revision):
    """
    Revision base class for use with GcdLink data objects.

    Unlike regular data objects, these objects are truly deleted from
    the database when they are no longer needed, which requires additional
    handling in the revisions.
    """
    class Meta:
        abstract = True

    def _pre_delete(self, changes):
        for revision in self.source.revisions.all():
            # Unhook the revisions because the data link object
            # will be truly deleted, not just marked inactive.
            revision.series_bond_id = None
            revision.save()


class PublisherRevisionBase(Revision):
    class Meta:
        abstract = True

    name = models.CharField(max_length=255)

    year_began = models.IntegerField(null=True, blank=True)
    year_ended = models.IntegerField(null=True, blank=True)
    year_began_uncertain = models.BooleanField(default=False)
    year_ended_uncertain = models.BooleanField(default=False)

    notes = models.TextField(blank=True)
    keywords = models.TextField(blank=True, default='')
    url = models.URLField(blank=True)


class PublisherRevision(PublisherRevisionBase):
    class Meta:
        db_table = 'oi_publisher_revision'
        ordering = ['-created', '-id']

    objects = RevisionManager()

    publisher = models.ForeignKey('gcd.Publisher', null=True,
                                  related_name='revisions')

    country = models.ForeignKey('gcd.Country', db_index=True)

    # Deprecated fields about relating publishers/imprints to each other
    is_master = models.BooleanField(default=True, db_index=True)
    parent = models.ForeignKey('gcd.Publisher', default=None,
                               null=True, blank=True, db_index=True,
                               related_name='imprint_revisions')

    date_inferred = models.BooleanField(default=False)

    source_name = 'publisher'
    source_class = Publisher

    @property
    def source(self):
        return self.publisher

    @source.setter
    def source(self, value):
        self.publisher = value


class IndiciaPublisherRevision(PublisherRevisionBase):
    class Meta:
        db_table = 'oi_indicia_publisher_revision'
        ordering = ['-created', '-id']

    objects = RevisionManager()

    indicia_publisher = models.ForeignKey('gcd.IndiciaPublisher', null=True,
                                          related_name='revisions')

    is_surrogate = models.BooleanField(default=False)

    country = models.ForeignKey('gcd.Country', db_index=True,
                                related_name='indicia_publishers_revisions')

    parent = models.ForeignKey('gcd.Publisher',
                               null=True, blank=True, db_index=True,
                               related_name='indicia_publisher_revisions')

    source_name = 'indicia_publisher'
    source_class = IndiciaPublisher

    @property
    def source(self):
        return self.indicia_publisher

    @source.setter
    def source(self, value):
        self.indicia_publisher = value

    @classmethod
    def _get_parent_field_tuples(cls):
        return frozenset({('parent',)})

    def _do_complete_added_revision(self, parent):
        """
        Do the necessary processing to complete the fields of a new
        indicia publisher revision for adding a record before it can be saved.
        """
        self.parent = parent


class BrandGroupRevision(PublisherRevisionBase):
    class Meta:
        db_table = 'oi_brand_group_revision'
        ordering = ['-created', '-id']

    objects = RevisionManager()

    brand_group = models.ForeignKey('gcd.BrandGroup', null=True,
                                    related_name='revisions')

    parent = models.ForeignKey('gcd.Publisher',
                               null=True, blank=True, db_index=True,
                               related_name='brand_group_revisions')

    source_name = 'brand_group'
    source_class = BrandGroup

    @property
    def source(self):
        return self.brand_group

    @source.setter
    def source(self, value):
        self.brand_group = value

    @classmethod
    def _get_parent_field_tuples(cls):
        return frozenset({('parent',)})

    def _do_complete_added_revision(self, parent):
        """
        Do the necessary processing to complete the fields of a new
        series revision for adding a record before it can be saved.
        """
        self.parent = parent

    def _post_adjust_stats(self, changes):
        if self.added:
            brand_revision = BrandRevision(
                changeset=self.changeset,
                name=self.name,
                year_began=self.year_began,
                year_ended=self.year_ended,
                year_began_uncertain=self.year_began_uncertain,
                year_ended_uncertain=self.year_ended_uncertain)
            brand_revision.save()
            brand_revision.group.add(self.brand_group)
            brand_revision.commit_to_display()


class BrandRevision(PublisherRevisionBase):
    class Meta:
        db_table = 'oi_brand_revision'
        ordering = ['-created', '-id']

    objects = RevisionManager()

    brand = models.ForeignKey('gcd.Brand', null=True, related_name='revisions')
    # parent needs to be kept for old revisions
    parent = models.ForeignKey('gcd.Publisher',
                               null=True, blank=True, db_index=True,
                               related_name='brand_revisions')
    group = models.ManyToManyField('gcd.BrandGroup', blank=False,
                                   related_name='brand_revisions')

    source_name = 'brand'
    source_class = Brand

    @property
    def source(self):
        return self.brand

    @source.setter
    def source(self, value):
        self.brand = value

    @property
    def issue_count(self):
        if self.brand is None:
            return 0
        return self.brand.issue_count

    def _post_adjust_stats(self, changes):
        if self.added:
            if self.brand.group.count() != 1:
                raise NotImplementedError

            group = self.brand.group.get()
            use = BrandUseRevision(
                changeset=self.changeset,
                emblem=self.brand,
                publisher=group.parent,
                year_began=self.year_began,
                year_began_uncertain=self.year_began_uncertain,
                year_ended=self.year_ended,
                year_ended_uncertain=self.year_ended_uncertain)
            use.save()
            use.commit_to_display()


class BrandUseRevision(Revision):
    class Meta:
        db_table = 'oi_brand_use_revision'
        ordering = ['-created', '-id']

    objects = RevisionManager()

    brand_use = models.ForeignKey('gcd.BrandUse', null=True,
                                  related_name='revisions')

    emblem = models.ForeignKey('gcd.Brand', null=True,
                               related_name='use_revisions')

    publisher = models.ForeignKey('gcd.Publisher', null=True, db_index=True,
                                  related_name='brand_use_revisions')

    year_began = models.IntegerField(db_index=True, null=True)
    year_ended = models.IntegerField(null=True)
    year_began_uncertain = models.BooleanField(default=False)
    year_ended_uncertain = models.BooleanField(default=False)
    notes = models.TextField(max_length=255, blank=True)

    source_name = 'brand_use'
    source_class = BrandUse

    @property
    def source(self):
        return self.brand_use

    @source.setter
    def source(self, value):
        self.brand_use = value

    def _do_complete_added_revision(self, emblem, publisher):
        """
        Do the necessary processing to complete the fields of a new
        BrandUse revision for adding a record before it can be saved.
        """
        self.publisher = publisher
        self.emblem = emblem


class CoverRevision(Revision):
    class Meta:
        db_table = 'oi_cover_revision'
        ordering = ['-created', '-id']

    objects = RevisionManager()

    cover = models.ForeignKey(Cover, null=True, related_name='revisions')
    issue = models.ForeignKey(Issue, related_name='cover_revisions')

    marked = models.BooleanField(default=False)
    is_replacement = models.BooleanField(default=False)
    is_wraparound = models.BooleanField(default=False)
    front_left = models.IntegerField(default=0, null=True)
    front_right = models.IntegerField(default=0, null=True)
    front_bottom = models.IntegerField(default=0, null=True)
    front_top = models.IntegerField(default=0, null=True)

    file_source = models.CharField(max_length=255, null=True)

    source_name = 'cover'
    source_class = Cover

    @property
    def source(self):
        return self.cover

    @source.setter
    def source(self, value):
        self.cover = value

    @classmethod
    def _get_excluded_field_names(cls):
        return frozenset(
            super(CoverRevision, cls)._get_excluded_field_names() |
            {
                'is_wraparound',
                'front_left',
                'front_right',
                'front_top',
                'front_bottom',
            }
        )

    @classmethod
    def _get_stats_category_field_tuples(cls):
        return frozenset({('issue', 'series', 'country',),
                          ('issue', 'series', 'language',)})

    def commit_to_display(self, clear_reservation=True):
        # the file handling is in the view/covers code
        cover = self.cover

        if cover is None:
            # check for variants having added issue records
            issue_revisions = self.changeset.issuerevisions.all()
            if len(issue_revisions) == 0:
                cover = Cover(issue=self.issue)
            elif len(issue_revisions) == 1:
                if not issue_revisions[0].issue:
                    issue_revisions[0].commit_to_display()
                cover = Cover(issue=issue_revisions[0].issue)
                self.issue = cover.issue
            else:
                raise NotImplementedError
            cover.save()
        elif self.deleted:
            cover.delete()
            cover.save()
            update_count('covers', -1,
                         language=cover.issue.series.language,
                         country=cover.issue.series.country)
            if cover.issue.series.scan_count() == 0:
                series = cover.issue.series
                series.has_gallery = False
                series.save()
            return

        if clear_reservation:
            cover.reserved = False

        if self.cover and self.is_replacement is False:
            # this is a move of a cover
            if self.changeset.change_type in [CTYPES['variant_add'],
                                              CTYPES['two_issues']]:
                old_issue = cover.issue
                issue_rev = self.changeset.issuerevisions\
                                          .exclude(issue=old_issue).get()
                cover.issue = issue_rev.issue
                cover.save()
                if issue_rev.series != old_issue.series:
                    if (issue_rev.series.language !=
                        old_issue.series.language) \
                       or (issue_rev.series.country !=
                           old_issue.series.country):
                        update_count('covers', -1,
                                     language=old_issue.series.language,
                                     country=old_issue.series.country)
                        update_count('covers', 1,
                                     language=issue_rev.series.language,
                                     country=issue_rev.series.country)
                    if not issue_rev.series.has_gallery:
                        issue_rev.series.has_gallery = True
                        issue_rev.series.save()
                    if old_issue.series.scan_count() == 0:
                        old_issue.series.has_gallery = False
                        old_issue.series.save()
            else:
                # implement in case we do different kind if cover moves
                raise NotImplementedError
        else:
            from apps.oi.covers import copy_approved_cover
            if self.cover is None:
                self.cover = cover
                self.save()
                update_count('covers', 1,
                             language=cover.issue.series.language,
                             country=cover.issue.series.country)
                if not cover.issue.series.has_gallery:
                    series = cover.issue.series
                    series.has_gallery = True
                    series.save()
            copy_approved_cover(self)
            cover.marked = self.marked
            cover.last_upload = self.changeset.comments \
                                    .latest('created').created
            cover.is_wraparound = self.is_wraparound
            cover.front_left = self.front_left
            cover.front_right = self.front_right
            cover.front_top = self.front_top
            cover.front_bottom = self.front_bottom
            cover.save()


class SeriesRevision(Revision):
    class Meta:
        db_table = 'oi_series_revision'
        ordering = ['-created', '-id']

    objects = RevisionManager()

    series = models.ForeignKey(Series, null=True, related_name='revisions')

    # When adding a series, this requests the ongoing reservation upon
    # approval of the new series.  The request will be granted unless the
    # indexer has reached their maximum number of ongoing reservations
    # at the time of approval.
    reservation_requested = models.BooleanField(default=False)

    name = models.CharField(max_length=255)
    leading_article = models.BooleanField(default=False)

    # The "format" field is a legacy field that is being split into
    # color, dimensions, paper_stock, binding, and publishing_format
    format = models.CharField(max_length=255, blank=True)
    color = models.CharField(max_length=255, blank=True)
    dimensions = models.CharField(max_length=255, blank=True)
    paper_stock = models.CharField(max_length=255, blank=True)
    binding = models.CharField(max_length=255, blank=True)
    publishing_format = models.CharField(max_length=255, blank=True)
    publication_type = models.ForeignKey(SeriesPublicationType,
                                         null=True, blank=True)

    year_began = models.IntegerField()
    year_ended = models.IntegerField(null=True, blank=True)
    year_began_uncertain = models.BooleanField(default=False)
    year_ended_uncertain = models.BooleanField(default=False)
    is_current = models.BooleanField(default=False)

    publication_notes = models.TextField(blank=True)

    # Fields for tracking relationships between series.
    # Crossref fields don't appear to really be used- nearly all null.
    # TODO: what's a crossref field?  Was that a field in the old DB?
    #       appears to be a stale comment of some sort.  The tracking
    #       notes field was definitely used plenty.
    tracking_notes = models.TextField(blank=True)

    # Fields for handling the presence of certain issue fields
    has_barcode = models.BooleanField(default=False)
    has_indicia_frequency = models.BooleanField(default=False)
    has_isbn = models.BooleanField(default=False, verbose_name='Has ISBN')
    has_issue_title = models.BooleanField(default=False)
    has_volume = models.BooleanField(default=False)
    has_rating = models.BooleanField(default=False)

    is_comics_publication = models.BooleanField(default=False)
    is_singleton = models.BooleanField(default=False)

    notes = models.TextField(blank=True)
    keywords = models.TextField(blank=True, default='')

    # Country and Language info.
    country = models.ForeignKey(Country, related_name='series_revisions')
    language = models.ForeignKey(Language, related_name='series_revisions')

    # Fields related to the publishers table.
    publisher = models.ForeignKey(Publisher, related_name='series_revisions')
    imprint = models.ForeignKey(Publisher, null=True, blank=True, default=None,
                                related_name='imprint_series_revisions')
    date_inferred = models.BooleanField(default=False)

    source_name = 'series'
    source_class = Series

    @property
    def source(self):
        return self.series

    @source.setter
    def source(self, value):
        self.series = value

    @classmethod
    def _get_excluded_field_names(cls):
        return frozenset(
            super(SeriesRevision, cls)._get_excluded_field_names() |
            {'open_reserve', 'publication_dates'}
        )

    @classmethod
    def _get_parent_field_tuples(cls):
        return frozenset({('publisher',)})

    @classmethod
    def _get_major_flag_field_tuples(self):
        return frozenset({
            ('is_comics_publication',),
            ('is_current',),
            ('is_singleton',),
        })

    @classmethod
    def _get_deprecated_field_names(cls):
        return frozenset({'format'})

    def _do_complete_added_revision(self, publisher):
        """
        Do the necessary processing to complete the fields of a new
        series revision for adding a record before it can be saved.
        """
        self.publisher = publisher

    def _pre_stats_measurement(self, changes):
        # Handle deletion of the singleton issue before getting the
        # series stat counts to avoid double-counting the deletion.
        if self.deleted and self.series.is_singleton:
            issue_revision = IssueRevision.clone(
                instance=self.series.issue_set[0], changeset=self.changeset)
            issue_revision.deleted = True
            issue_revision.save()
            issue_revision.commit_to_display()

    def _post_assign_fields(self, changes):
        if self.leading_article:
            self.series.sort_name = remove_leading_article(self.name)
        else:
            self.series.sort_name = self.name

    def _pre_save_object(self, changes):
        if changes['from is_current']:
            reservation = self.series.get_ongoing_reservation()
            reservation.delete()

        if changes['to is_comics_publication']:
            # TODO: But don't we count covers for some non-comics?
            self.series.has_gallery = bool(self.series.scan_count())

    def _post_adjust_stats(self, changes):
        # Handle adding the singleton issue last, to avoid double-counting
        # the addition in statistics.
        if changes['to is_singleton'] and self.series.issue_count == 0:
            issue_revision = IssueRevision(changeset=self.changeset,
                                           series=self.series,
                                           after=None,
                                           number='[nn]',
                                           publication_date=self.year_began)
            # We assume that a non-four-digit year is a typo of some
            # sort, and do not propagate it.  The approval process
            # should catch that sort of thing.
            # TODO: Consider a validator on year_began?
            if len(unicode(self.year_began)) == 4:
                issue_revision.key_date = '%d-00-00' % self.year_began
            issue_revision.save()
            issue_revision.commit_to_display()


class SeriesBondRevision(LinkRevision):
    class Meta:
        db_table = 'oi_series_bond_revision'
        ordering = ['-created', '-id']
        get_latest_by = "created"

    objects = RevisionManager()

    series_bond = models.ForeignKey(SeriesBond, null=True,
                                    related_name='revisions')

    origin = models.ForeignKey(Series, null=True,
                               related_name='origin_bond_revisions')
    origin_issue = models.ForeignKey(
        Issue, null=True, related_name='origin_series_bond_revisions')
    target = models.ForeignKey(Series, null=True,
                               related_name='target_bond_revisions')
    target_issue = models.ForeignKey(
        Issue, null=True, related_name='target_series_bond_revisions')

    bond_type = models.ForeignKey(SeriesBondType, null=True,
                                  related_name='bond_revisions')
    notes = models.TextField(max_length=255, default='', blank=True)

    source_name = 'series_bond'
    source_class = SeriesBond

    @property
    def source(self):
        return self.series_bond

    @source.setter
    def source(self, value):
        self.series_bond = value


class IssueRevision(Revision):
    class Meta:
        db_table = 'oi_issue_revision'
        ordering = ['-created', '-id']

    objects = RevisionManager()

    issue = models.ForeignKey(Issue, null=True, related_name='revisions')

    # If not null, insert or move the issue after the given issue
    # when saving back the DB. If null, place at the beginning of
    # the series.
    after = models.ForeignKey(
        Issue, null=True, blank=True, related_name='after_revisions',
        verbose_name='Add this issue after')

    # This is used *only* for multiple issues within the same changeset.
    # It does NOT correspond directly to gcd_issue.sort_code, which must be
    # calculated at the time the revision is committed.
    revision_sort_code = models.IntegerField(null=True)

    # When adding an issue, this requests the reservation upon approval of
    # the new issue.  The request will be granted unless an ongoing reservation
    # is in place at the time of approval.
    reservation_requested = models.BooleanField(
        default=False, verbose_name='Request reservation')

    number = models.CharField(max_length=50)

    title = models.CharField(max_length=255, default='', blank=True)
    no_title = models.BooleanField(default=False)

    volume = models.CharField(max_length=50, blank=True, default='')
    no_volume = models.BooleanField(default=False)
    display_volume_with_number = models.BooleanField(default=False)
    variant_of = models.ForeignKey(Issue, null=True,
                                   related_name='variant_revisions')
    variant_name = models.CharField(max_length=255, blank=True, default='')

    publication_date = models.CharField(max_length=255, blank=True, default='')
    key_date = models.CharField(
        max_length=10, blank=True, default='',
        validators=[RegexValidator(
            r'^(17|18|19|20)\d{2}(\.|-)(0[0-9]|1[0-3])(\.|-)\d{2}$')])
    year_on_sale = models.IntegerField(db_index=True, null=True, blank=True)
    month_on_sale = models.IntegerField(db_index=True, null=True, blank=True)
    day_on_sale = models.IntegerField(db_index=True, null=True, blank=True)
    on_sale_date_uncertain = models.BooleanField(default=False)
    indicia_frequency = models.CharField(max_length=255, blank=True,
                                         default='')
    no_indicia_frequency = models.BooleanField(default=False)

    price = models.CharField(max_length=255, blank=True, default='')
    page_count = models.DecimalField(max_digits=10, decimal_places=3,
                                     null=True, blank=True, default=None)
    page_count_uncertain = models.BooleanField(default=False)

    editing = models.TextField(blank=True, default='')
    no_editing = models.BooleanField(default=False)
    notes = models.TextField(blank=True, default='')
    keywords = models.TextField(blank=True, default='')

    series = models.ForeignKey(Series, related_name='issue_revisions')
    indicia_publisher = models.ForeignKey(
        IndiciaPublisher, null=True, blank=True, default=None,
        related_name='issue_revisions',
        verbose_name='indicia/colophon publisher')
    indicia_pub_not_printed = models.BooleanField(
        default=False,
        verbose_name='indicia/colophon pub. not printed')
    brand = models.ForeignKey(
        Brand, null=True, default=None, blank=True,
        related_name='issue_revisions', verbose_name='brand emblem')
    no_brand = models.BooleanField(default=False,
                                   verbose_name='no brand emblem')

    isbn = models.CharField(
        max_length=32, blank=True, default='', verbose_name='ISBN')
    no_isbn = models.BooleanField(default=False, verbose_name='No ISBN')

    barcode = models.CharField(max_length=38, blank=True, default='')
    no_barcode = models.BooleanField(default=False)

    rating = models.CharField(max_length=255, blank=True, default='',
                              verbose_name="Publisher's age guidelines")
    no_rating = models.BooleanField(
        default=False, verbose_name="No publisher's age guidelines")

    date_inferred = models.BooleanField(default=False)

    source_name = 'issue'
    source_class = Issue

    @property
    def source(self):
        return self.issue

    @source.setter
    def source(self, value):
        self.issue = value

    @property
    def series_changed(self):
        """ True if the series changed and this is neither add nor delete. """
        return ((not self.deleted) and
                (self.previous_revision is not None) and
                self.previous_revision.series != self.series)

    @classmethod
    def _get_stats_category_field_tuples(cls):
        return frozenset({('series', 'country',), ('series', 'language',)})

    @classmethod
    def _get_conditional_field_tuple_mapping(cls):
        has_title = ('series', 'has_issue_title')
        has_barcode = ('series', 'has_barcode')
        has_isbn = ('series', 'has_isbn')
        has_volume = ('series', 'has_volume')
        has_ind_freq = ('series', 'has_indicia_frequency')
        return {
            'title': has_title,
            'no_title': has_title,
            'barcode': has_barcode,
            'no_barcode': has_barcode,
            'isbn': has_isbn,
            'no_isbn': has_isbn,
            'valid_isbn': has_isbn,
            'volume': has_volume,
            'no_volume': has_volume,
            'display_volume_with_issue': has_volume,
            'indicia_frequency': has_ind_freq,
            'no_indicia_frequency': has_ind_freq,
        }

    @classmethod
    def _get_parent_field_tuples(cls):
        # There are several routes to a publisher object, but
        # if there are differences, it is the publisher of the series
        # that should get the count adjustments.
        return frozenset({
            ('series',),
            ('series', 'publisher'),
            ('indicia_publisher',),
            ('brand',),
            ('brand', 'group'),
        })

    def _pre_initial_save(self):
        if self.issue.on_sale_date:
            (self.year_on_sale,
             self.month_on_sale,
             self.day_on_sale) = on_sale_date_fields(self.issue.on_sale_date)

    def _do_complete_added_revision(self, series, variant_of=None):
        """
        Do the necessary processing to complete the fields of a new
        issue revision for adding a record before it can be saved.
        """
        self.series = series
        if variant_of:
            self.variant_of = variant_of

    def _same_series_revisions(self):
        return self.changeset.issuerevisions.filter(series=self.series)

    def _same_series_open_with_after(self):
        return self._same_series_revisions().filter(after__isnull=False,
                                                    committed=None)

    def _open_prereq_revisions(self):
        # Adds and moves go first to last, deletes last to first.
        sort = '-revision_sort_code' if self.deleted else 'revision_sort_code'
        return self._same_series_revisions().exclude(id=self.id) \
                                            .filter(committed=None) \
                                            .order_by(sort)

    def _committed_prereq_revisions(self):
        # We pop off of open prereqs and push onto committed, so reverse sort.
        sort = 'revision_sort_code' if self.deleted else '-revision_sort_code'
        return self._same_series_revisions().exclude(id=self.id) \
                                            .filter(committed=True) \
                                            .order_by(sort)

    def _post_commit_to_display(self):
        if self.changeset.changeset_action() == ACTION_MODIFY and \
           self.issue.is_indexed != INDEXED['skeleton']:
            RecentIndexedIssue.objects.update_recents(self.issue)

    def commit_to_display(self, clear_reservation=True, space_count=1):
        issue = self.issue
        check_series_order = None

        if issue is None:
            if self.after is None:
                after_code = -1
            else:
                after_code = self.after.sort_code

            # sort_codes tend to be sequential, so just always increment them
            # out of the way.
            later_issues = Issue.objects.filter(
                series=self.series,
                sort_code__gt=after_code).order_by('-sort_code')

            # Make space for the issue(s) being added.  The changeset will
            # pass a larger number or zero in order to make all necessary
            # space for a multiple add on the first pass, and then not
            # have to update this for the remaining issues.
            if space_count > 0:
                # Unique constraint prevents us from doing this:
                # later_issues.update(sort_code=F('sort_code') + space_count)
                # which is vastly more efficient.  TODO: revisit.
                for later_issue in later_issues:
                    later_issue.sort_code += space_count
                    later_issue.save()

            issue = Issue(sort_code=after_code + 1)
            if self.variant_of:
                if self.series.is_comics_publication:
                    update_count('variant issues', 1,
                                 language=self.series.language,
                                 country=self.series.country)
            else:
                self.series.issue_count = F('issue_count') + 1
                # do NOT save the series here, it gets saved later in
                # self._check_first_last(), if we save here as well
                # the issue_count goes up by 2
                if self.series.is_comics_publication:
                    self.series.publisher.issue_count = F('issue_count') + 1
                    self.series.publisher.save()
                    if self.brand:
                        self.brand.issue_count = F('issue_count') + 1
                        self.brand.save()
                        for group in self.brand.group.all():
                            group.issue_count = F('issue_count') + 1
                            group.save()
                    if self.indicia_publisher:
                        self.indicia_publisher.issue_count = \
                            F('issue_count') + 1
                        self.indicia_publisher.save()
                    update_count('issues', 1, language=self.series.language,
                                 country=self.series.country)

        elif self.deleted:
            if self.variant_of:
                if self.series.is_comics_publication:
                    update_count('variant issues', -1,
                                 language=self.series.language,
                                 country=self.series.country)
            else:
                self.series.issue_count = F('issue_count') - 1
                # do NOT save the series here, it gets saved later in
                # self._check_first_last(), if we save here as well
                # the issue_count goes down by 2
                if self.series.is_comics_publication:
                    self.series.publisher.issue_count = F('issue_count') - 1
                    self.series.publisher.save()
                    if self.brand:
                        self.brand.issue_count = F('issue_count') - 1
                        self.brand.save()
                        for group in self.brand.group.all():
                            group.issue_count = F('issue_count') - 1
                            group.save()
                    if self.indicia_publisher:
                        self.indicia_publisher.issue_count = \
                            F('issue_count') - 1
                        self.indicia_publisher.save()
                    update_count('issues', -1, language=issue.series.language,
                                 country=issue.series.country)
            issue.delete()
            self._check_first_last()
            return

        else:
            if not self.variant_of and self.series.is_comics_publication:
                if self.brand != issue.brand:
                    if self.brand:
                        self.brand.issue_count = F('issue_count') + 1
                        self.brand.save()
                        for group in self.brand.group.all():
                            group.issue_count = F('issue_count') + 1
                            group.save()
                    if issue.brand:
                        issue.brand.issue_count = F('issue_count') - 1
                        issue.brand.save()
                        for group in issue.brand.group.all():
                            group.issue_count = F('issue_count') - 1
                            group.save()
                if self.indicia_publisher != issue.indicia_publisher:
                    if self.indicia_publisher:
                        self.indicia_publisher.issue_count = \
                            F('issue_count') + 1
                        self.indicia_publisher.save()
                    if issue.indicia_publisher:
                        issue.indicia_publisher.issue_count = \
                            F('issue_count') - 1
                        issue.indicia_publisher.save()
            if self.series != issue.series:
                if self.series.issue_count:
                    # move to the end of the new series
                    issue.sort_code = (self.series.active_issues()
                                                  .latest('sort_code')
                                                  .sort_code) + 1
                else:
                    issue.sort_code = 0
                # update counts
                if self.variant_of:
                    if self.series.language != issue.series.language or \
                       self.series.country != issue.series.country:
                        if self.series.is_comics_publication:
                            update_count('variant issues', 1,
                                         language=self.series.language,
                                         country=self.series.country)
                        if issue.series.is_comics_publication:
                            update_count('variant issues', -1,
                                         language=issue.series.language,
                                         country=issue.series.country)
                else:
                    self.series.issue_count = F('issue_count') + 1
                    issue.series.issue_count = F('issue_count') - 1
                    if self.series.publisher != issue.series.publisher:
                        if self.series.is_comics_publication:
                            if self.series.publisher:
                                self.series.publisher.issue_count = \
                                    F('issue_count') + 1
                                self.series.publisher.save()
                        if issue.series.is_comics_publication:
                            if issue.series.publisher:
                                issue.series.publisher.issue_count = \
                                    F('issue_count') - 1
                                issue.series.publisher.save()
                    if self.series.language != issue.series.language or \
                       self.series.country != issue.series.country:
                        if self.series.is_comics_publication:
                            update_count('issues', 1,
                                         language=self.series.language,
                                         country=self.series.country)
                        if issue.series.is_comics_publication:
                            update_count('issues', -1,
                                         language=issue.series.language,
                                         country=issue.series.country)
                        story_count = self.issue.active_stories().count()
                        update_count('stories', story_count,
                                     language=self.series.language,
                                     country=self.series.country)
                        update_count('stories', -story_count,
                                     language=issue.series.language,
                                     country=issue.series.country)
                        cover_count = self.issue.active_covers().count()
                        update_count('covers', cover_count,
                                     language=self.series.language,
                                     country=self.series.country)
                        update_count('covers', -cover_count,
                                     language=issue.series.language,
                                     country=issue.series.country)

                check_series_order = issue.series
                # new series might have gallery after move
                # do NOT save the series here, it gets saved later
                if self.series.has_gallery is False:
                    if issue.active_covers().count():
                        self.series.has_gallery = True
                # old series might have lost gallery after move
                if issue.series.scan_count() == \
                   issue.active_covers().count():
                    issue.series.has_gallery = False

        issue.number = self.number
        # only if the series has_field is True write to issue
        if self.series.has_issue_title:
            issue.title = self.title
            issue.no_title = self.no_title
        # handle case when series has_field changes during lifetime
        # of issue changeset, then changeset resets to issue data
        else:
            self.title = issue.title
            self.no_title = issue.no_title
            self.save()

        if self.series.has_volume:
            issue.volume = self.volume
            issue.no_volume = self.no_volume
            issue.display_volume_with_number = self.display_volume_with_number
        else:
            self.volume = issue.volume
            self.no_volume = issue.no_volume
            self.display_volume_with_number = issue.display_volume_with_number
            self.save()

        issue.variant_of = self.variant_of
        issue.variant_name = self.variant_name

        issue.publication_date = self.publication_date
        issue.key_date = self.key_date
        issue.on_sale_date = on_sale_date_as_string(self)
        issue.on_sale_date_uncertain = self.on_sale_date_uncertain

        if self.series.has_indicia_frequency:
            issue.indicia_frequency = self.indicia_frequency
            issue.no_indicia_frequency = self.no_indicia_frequency
        else:
            self.indicia_frequency = issue.indicia_frequency
            self.no_indicia_frequency = issue.no_indicia_frequency
            self.save()

        issue.price = self.price
        issue.page_count = self.page_count
        issue.page_count_uncertain = self.page_count_uncertain

        issue.editing = self.editing
        issue.no_editing = self.no_editing
        issue.notes = self.notes
        issue.series = self.series
        issue.indicia_publisher = self.indicia_publisher
        issue.indicia_pub_not_printed = self.indicia_pub_not_printed
        issue.brand = self.brand
        issue.no_brand = self.no_brand

        if self.series.has_isbn:
            issue.isbn = self.isbn
            issue.no_isbn = self.no_isbn
            issue.valid_isbn = validated_isbn(issue.isbn)
        else:
            self.isbn = issue.isbn
            self.no_isbn = issue.no_isbn
            self.save()

        if self.series.has_barcode:
            issue.barcode = self.barcode
            issue.no_barcode = self.no_barcode
        else:
            self.barcode = issue.barcode
            self.no_barcode = issue.no_barcode
            self.save()

        if self.series.has_rating:
            issue.rating = self.rating
            issue.no_rating = self.no_rating
        else:
            self.rating = issue.rating
            self.no_rating = issue.no_rating
            self.save()

        if clear_reservation:
            issue.reserved = False

        issue.save()
        save_keywords(self, issue)
        issue.save()
        if self.issue is None:
            self.issue = issue
            self.save()
            self._check_first_last()
            for story in self.changeset.storyrevisions.filter(issue=None):
                story.issue = issue
                story.save()

        if check_series_order:
            set_series_first_last(check_series_order)
            self._check_first_last()

    def _check_first_last(self):
        set_series_first_last(self.series)


class StoryRevision(Revision):
    class Meta:
        db_table = 'oi_story_revision'
        ordering = ['-created', '-id']

    objects = RevisionManager()

    story = models.ForeignKey(Story, null=True,
                              related_name='revisions')

    title = models.CharField(max_length=255, blank=True)
    title_inferred = models.BooleanField(default=False)
    feature = models.CharField(max_length=255, blank=True)
    type = models.ForeignKey(StoryType)
    sequence_number = models.IntegerField()

    page_count = models.DecimalField(max_digits=10, decimal_places=3,
                                     null=True, blank=True)
    page_count_uncertain = models.BooleanField(default=False)

    script = models.TextField(blank=True)
    pencils = models.TextField(blank=True)
    inks = models.TextField(blank=True)
    colors = models.TextField(blank=True)
    letters = models.TextField(blank=True)
    editing = models.TextField(blank=True)

    no_script = models.BooleanField(default=False)
    no_pencils = models.BooleanField(default=False)
    no_inks = models.BooleanField(default=False)
    no_colors = models.BooleanField(default=False)
    no_letters = models.BooleanField(default=False)
    no_editing = models.BooleanField(default=False)

    job_number = models.CharField(max_length=25, blank=True)
    genre = models.CharField(max_length=255, blank=True)
    characters = models.TextField(blank=True)
    synopsis = models.TextField(blank=True)
    reprint_notes = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    keywords = models.TextField(blank=True, default='')

    issue = models.ForeignKey(Issue, null=True, related_name='story_revisions')
    date_inferred = models.BooleanField(default=False)

    source_name = 'story'
    source_class = Story

    @property
    def source(self):
        return self.story

    @source.setter
    def source(self, value):
        self.story = value

    @classmethod
    def _get_stats_category_field_tuples(cls):
        return frozenset({('issue', 'series', 'country',),
                          ('issue', 'series', 'language',)})

    def _do_complete_added_revision(self, issue):
        """
        Do the necessary processing to complete the fields of a new
        story revision for adding a record before it can be saved.
        """
        self.issue = issue

    def commit_to_display(self, clear_reservation=True):
        story = self.story
        if story is None:
            story = Story()
            update_count('stories', 1, language=self.issue.series.language,
                         country=self.issue.series.country)
        elif self.deleted:
            if self.issue.is_indexed != INDEXED['skeleton']:
                if self.issue.set_indexed_status() == INDEXED['skeleton'] and \
                   self.issue.series.is_comics_publication:
                    update_count('issue indexes', -1,
                                 language=story.issue.series.language,
                                 country=story.issue.series.country)
            update_count('stories', -1, language=story.issue.series.language,
                         country=story.issue.series.country)
            self._reset_values()
            story.delete()
            return

        story.title = self.title
        story.title_inferred = self.title_inferred
        story.feature = self.feature
        if hasattr(story, 'issue') and (story.issue != self.issue):
            if story.issue.series.language != self.issue.series.language or \
               story.issue.series.country != self.issue.series.country:
                update_count('stories', 1,
                             language=self.issue.series.language,
                             country=self.issue.series.country)
                update_count('stories', -1,
                             language=story.issue.series.language,
                             country=story.issue.series.country)
            old_issue = story.issue
            story.issue = self.issue
            if old_issue.set_indexed_status() is False:
                update_count('issue indexes', -1,
                             language=old_issue.series.language,
                             country=old_issue.series.country)
        else:
            story.issue = self.issue
        story.page_count = self.page_count
        story.page_count_uncertain = self.page_count_uncertain

        story.script = self.script
        story.pencils = self.pencils
        story.inks = self.inks
        story.colors = self.colors
        story.letters = self.letters
        story.editing = self.editing

        story.no_script = self.no_script
        story.no_pencils = self.no_pencils
        story.no_inks = self.no_inks
        story.no_colors = self.no_colors
        story.no_letters = self.no_letters
        story.no_editing = self.no_editing

        story.notes = self.notes
        story.synopsis = self.synopsis
        story.reprint_notes = self.reprint_notes
        story.characters = self.characters
        story.genre = self.genre
        story.type = self.type
        story.job_number = self.job_number
        story.sequence_number = self.sequence_number

        if clear_reservation:
            story.reserved = False

        story.save()
        save_keywords(self, story)
        story.save()

        if self.story is None:
            self.story = story
            self.save()

        if self.issue.is_indexed == INDEXED['skeleton']:
            if self.issue.set_indexed_status() != INDEXED['skeleton'] and \
               self.issue.series.is_comics_publication:
                update_count('issue indexes', 1,
                             language=self.issue.series.language,
                             country=self.issue.series.country)
        else:
            if self.issue.set_indexed_status() == INDEXED['skeleton'] and \
               self.issue.series.is_comics_publication:
                update_count('issue indexes', -1,
                             language=self.issue.series.language,
                             country=self.issue.series.country)


class ReprintRevisionManager(RevisionManager):

    def _do_create_revision(self, reprint, changeset):
        """
        Helper delegate to do the class-specific work of clone_revision.
        """
        if isinstance(reprint, Reprint):
            previous_revision = ReprintRevision.objects.get(
                reprint=reprint, next_revision=None,
                changeset__state=states.APPROVED)
            revision = ReprintRevision(
                # revision-specific fields:
                reprint=reprint,
                in_type=REPRINT_TYPES['story_to_story'],
                # copied fields:
                origin_story=reprint.origin,
                target_story=reprint.target,
            )
        if isinstance(reprint, ReprintFromIssue):
            previous_revision = ReprintRevision.objects.get(
                reprint_from_issue=reprint, next_revision=None,
                changeset__state=states.APPROVED)
            revision = ReprintRevision(
                # revision-specific fields:
                reprint_from_issue=reprint,
                in_type=REPRINT_TYPES['issue_to_story'],
                # copied fields:
                target_story=reprint.target,
                origin_issue=reprint.origin_issue,
            )
        if isinstance(reprint, ReprintToIssue):
            previous_revision = ReprintRevision.objects.get(
                reprint_to_issue=reprint, next_revision=None,
                changeset__state=states.APPROVED)
            revision = ReprintRevision(
                # revision-specific fields:
                reprint_to_issue=reprint,
                in_type=REPRINT_TYPES['story_to_issue'],
                # copied fields:
                origin_story=reprint.origin,
                target_issue=reprint.target_issue,
            )
        if isinstance(reprint, IssueReprint):
            previous_revision = ReprintRevision.objects.get(
                issue_reprint=reprint, next_revision=None,
                changeset__state=states.APPROVED)
            revision = ReprintRevision(
                # revision-specific fields:
                issue_reprint=reprint,
                in_type=REPRINT_TYPES['issue_to_issue'],
                # copied fields:
                origin_issue=reprint.origin_issue,
                target_issue=reprint.target_issue,
            )
        revision.previous_revision = previous_revision
        revision.changeset = changeset
        revision.notes = reprint.notes
        revision.save()
        return revision


def get_reprint_field_list():
    return ['notes']


class ReprintRevision(Revision):
    """
    One Revision Class for all four types of reprints.

    Otherwise we would have to generate reprint revisions while editing one
    link, e.g. changing an issue_to_story reprint to a story_to_story one, or
    changing reprint direction from issue_to_story to story_to_issue.
    """
    class Meta:
        db_table = 'oi_reprint_revision'
        ordering = ['-created', '-id']
        get_latest_by = "created"

    objects = ReprintRevisionManager()

    reprint = models.ForeignKey(Reprint, null=True,
                                related_name='revisions')
    reprint_from_issue = models.ForeignKey(ReprintFromIssue, null=True,
                                           related_name='revisions')
    reprint_to_issue = models.ForeignKey(ReprintToIssue, null=True,
                                         related_name='revisions')
    issue_reprint = models.ForeignKey(IssueReprint, null=True,
                                      related_name='revisions')

    origin_story = models.ForeignKey(Story, null=True,
                                     related_name='origin_reprint_revisions')
    origin_revision = models.ForeignKey(
        StoryRevision, null=True, related_name='origin_reprint_revisions')
    origin_issue = models.ForeignKey(
        Issue, null=True, related_name='origin_reprint_revisions')

    target_story = models.ForeignKey(Story, null=True,
                                     related_name='target_reprint_revisions')
    target_revision = models.ForeignKey(
        StoryRevision, null=True, related_name='target_reprint_revisions')
    target_issue = models.ForeignKey(Issue, null=True,
                                     related_name='target_reprint_revisions')

    notes = models.TextField(max_length=255, default='')

    in_type = models.IntegerField(db_index=True, null=True)
    out_type = models.IntegerField(db_index=True, null=True)

    @property
    def source(self):
        if self.deleted and self.changeset.state == states.APPROVED:
            return None
        if self.out_type is not None:
            reprint_type = self.out_type
        elif self.in_type is not None:
            reprint_type = self.in_type
        else:
            return None
        # reprint link objects can be deleted, so the source may be gone
        # could access source for change history, so catch it
        if reprint_type == REPRINT_TYPES['story_to_story'] and \
           self.reprint:
            return self.reprint
        if reprint_type == REPRINT_TYPES['issue_to_story'] and \
           self.reprint_from_issue:
            return self.reprint_from_issue
        if reprint_type == REPRINT_TYPES['story_to_issue'] and \
           self.reprint_to_issue:
            return self.reprint_to_issue
        if reprint_type == REPRINT_TYPES['issue_to_issue'] and \
           self.issue_reprint:
            return self.issue_reprint
        # TODO is None the right return ? Maybe placeholder object ?
        return None

    @source.setter
    def source(self, value):
        # Hoping to ignore this until reprint data objects consolidated.
        raise NotImplementedError

    @property
    def source_class(self, value):
        # Hoping to ignore this until reprint data objects consolidated.
        raise NotImplementedError

    @property
    def source_name(self):
        return 'reprint'

    def commit_to_display(self, clear_reservation=True):
        if self.deleted:
            deleted_link = self.source
            field_name = REPRINT_FIELD[self.in_type] + '_id'
            for revision in deleted_link.revisions.all():
                setattr(revision, field_name, None)
                revision.save()
            deleted_link.delete()
            return
        # first figure out which reprint out_type it is, it depends
        # on which fields are set
        if self.origin_story or self.origin_revision:
            if self.origin_revision:
                self.origin_story = self.origin_revision.story
                self.origin_revision = None
            origin = self.origin_story
            if self.target_story or self.target_revision:
                if self.target_revision:
                    self.target_story = self.target_revision.story
                    self.target_revision = None
                out_type = REPRINT_TYPES['story_to_story']
                target = self.target_story
            else:
                out_type = REPRINT_TYPES['story_to_issue']
                # TODO: The following line was present but flake8 notes
                #       that the local variable "target_issue" is unused.
                # target_issue = self.target_issue
        else:  # issue is source
            if self.target_story or self.target_revision:
                if self.target_revision:
                    self.target_story = self.target_revision.story
                    self.target_revision = None
                out_type = REPRINT_TYPES['issue_to_story']
                target = self.target_story
            else:
                out_type = REPRINT_TYPES['issue_to_issue']

        if self.in_type is not None and self.in_type != out_type:
            deleted_link = self.source
            field_name = REPRINT_FIELD[self.in_type] + '_id'
            for revision in deleted_link.revisions.all():
                setattr(revision, field_name, None)
                revision.save()
            setattr(self, field_name, None)
            deleted_link.delete()
        self.out_type = out_type

        # actual save of the data
        if out_type == REPRINT_TYPES['story_to_story']:
            if self.in_type != out_type:
                self.reprint = Reprint.objects.create(origin=origin,
                                                      target=target,
                                                      notes=self.notes)
            else:
                self.reprint.origin = origin
                self.reprint.target = target
                self.reprint.notes = self.notes
                self.reprint.save()
        elif out_type == REPRINT_TYPES['issue_to_story']:
            if self.in_type != out_type:
                self.reprint_from_issue = ReprintFromIssue.objects.create(
                    origin_issue=self.origin_issue,
                    target=target,
                    notes=self.notes)
            else:
                self.reprint_from_issue.origin_issue = self.origin_issue
                self.reprint_from_issue.target = target
                self.reprint_from_issue.notes = self.notes
                self.reprint_from_issue.save()
        elif out_type == REPRINT_TYPES['story_to_issue']:
            if self.in_type != out_type:
                self.reprint_to_issue = ReprintToIssue.objects.create(
                    origin=origin,
                    target_issue=self.target_issue,
                    notes=self.notes)
            else:
                self.reprint_to_issue.origin = origin
                self.reprint_to_issue.target_issue = self.target_issue
                self.reprint_to_issue.notes = self.notes
                self.reprint_to_issue.save()
        elif out_type == REPRINT_TYPES['issue_to_issue']:
            if self.in_type != out_type:
                self.issue_reprint = IssueReprint.objects.create(
                    origin_issue=self.origin_issue,
                    target_issue=self.target_issue,
                    notes=self.notes)
            else:
                self.issue_reprint.origin_issue = self.origin_issue
                self.issue_reprint.target_issue = self.target_issue
                self.issue_reprint.notes = self.notes
                self.issue_reprint.save()

        if clear_reservation and self.source:
            reprint = self.source
            reprint.reserved = False
            reprint.save()

        self.save()


class Download(models.Model):
    """
    Track downloads of bulk data.  Description may contain the filesystem
    paths or other information about what was downloaded.
    """
    user = models.ForeignKey(User)
    description = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)


class ImageRevision(Revision):
    class Meta:
        db_table = 'oi_image_revision'
        ordering = ['created']

    objects = RevisionManager()

    image = models.ForeignKey(Image, null=True, related_name='revisions')

    content_type = models.ForeignKey(content_models.ContentType, null=True)
    object_id = models.PositiveIntegerField(db_index=True, null=True)
    object = generic_fields.GenericForeignKey('content_type', 'object_id')

    type = models.ForeignKey(ImageType)

    image_file = models.ImageField(upload_to='%s/%%m_%%Y' %
                                             settings.NEW_GENERIC_IMAGE_DIR)
    scaled_image = ImageSpecField([ResizeToFit(width=400)],
                                  source='image_file',
                                  format='JPEG', options={'quality': 90})

    marked = models.BooleanField(default=False)
    is_replacement = models.BooleanField(default=False)

    source_name = 'image'
    source_class = Image

    @property
    def source(self):
        return self.image

    @source.setter
    def source(self, value):
        self.image = value

    @classmethod
    def _get_excluded_field_names(cls):
        return frozenset(
            super(ImageRevision, cls)._get_excluded_field_names() |
            {'image_file', 'scaled_image', 'marked'}
        )

    def commit_to_display(self, clear_reservation=True):
        image = self.image
        if self.is_replacement:
            prev_rev = self.previous()
            # copy replaced image back to revision
            prev_rev.image_file.save(str(prev_rev.id) + '.jpg',
                                     content=image.image_file)
            image.image_file.delete()
        elif self.deleted:
            image.delete()
            return
        elif image is None:
            if self.type.unique and not self.is_replacement:
                if Image.objects.filter(
                        content_type=ContentType.objects
                                                .get_for_model(self.object),
                        object_id=self.object.id,
                        type=self.type,
                        deleted=False).count():
                    raise ValueError(
                        '%s has an %s. Additional images cannot be uploaded, '
                        'only replacements are possible.' %
                        (self.object, self.type.description))

            # first generate instance
            image = Image(content_type=self.content_type,
                          object_id=self.object_id,
                          type=self.type,
                          marked=self.marked)
            image.save()

        # then add the uploaded file
        image.image_file.save(str(image.id) + '.jpg', content=self.image_file)
        self.image_file.delete()
        self.image = image
        self.save()
        if clear_reservation:
            image.reserved = False
            image.save()
