# -*- coding: utf-8 -*-

from django.conf import settings
from django.db import models
from django.db.models import F
from django.contrib.auth.models import User
from django.contrib.contenttypes import models as content_models
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes import generic
from django.core.validators import RegexValidator

from imagekit.models import ImageSpecField
from imagekit.processors import ResizeToFit

from apps.oi import states

# We should just from apps.gcd import models as gcd_models, but that's
# a lot of little changes so for now tell flake8 noqa so it doesn't complain
from apps.gcd.models import *  # noqa
from apps.gcd.models.issue import INDEXED


CTYPES = {
    'publisher': 1,
    'series': 4,
}


def update_count(*args, **kwargs):
    # Just a dummy for now, always mocked in test cases.
    # Will be re-added as cases expand to cover CountStats.
    pass


def remove_leading_article(name):
    '''
    returns the name with the leading article (separated by "'"
    or whitespace) removed
    '''
    article_match = re.match(r"\S?\w+['\s]\s*(.*)$", name, re.UNICODE)
    if article_match:
        return article_match.group(1)
    else:
        return name


def get_keywords(source):
    return u'; '.join(unicode(i) for i in source.keywords.all()
                                                .order_by('name'))


def save_keywords(revision, source):
    if revision.keywords:
        source.keywords.set(*[x.strip() for x in revision.keywords.split(';')])
        revision.keywords = u'; '.join(
            unicode(i) for i in source.keywords.all().order_by('name'))
        revision.save()
    else:
        source.keywords.set()


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
    revision = generic.GenericForeignKey('content_type', 'revision_id')

    old_state = models.IntegerField()
    new_state = models.IntegerField()
    created = models.DateTimeField(auto_now_add=True, editable=False)


class RevisionLock(models.Model):
    """
    Indicates that a particular Changeset has a partocular row locked.

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
    locked_object = generic.GenericForeignKey('content_type', 'object_id')


class RevisionManager(models.Manager):
    """
    Custom manager base class for revisions.
    """

    def clone_revision(self, instance, instance_class,
                       changeset, check=True):
        """
        Given an existing instance, create a new revision based on it.

        This new revision will be where the edits are made.
        If there are no revisions, first save a baseline so that the pre-edit
        values are preserved.
        Entirely new publishers should be started by simply instantiating
        a new PublisherRevision directly.
        """
        if not isinstance(instance, instance_class):
            raise TypeError("Please supply a valid %s." % instance_class)

        revision = self._do_create_revision(instance,
                                            changeset=changeset)
        return revision

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

    A state column trackes the progress of the revision, which should
    eventually end in either the APPROVED or DISCARDED state.
    """
    class Meta:
        abstract = True

    changeset = models.ForeignKey(Changeset, related_name='%(class)ss')

    """
    If true, this revision deletes the object in question.  Other fields
    should not contain changes but should instead be a record of the object
    at the time of deletion and therefore match the previous revision.
    If changes are present, then they were never actually published and
    should be ignored in terms of history.
    """
    deleted = models.BooleanField(default=False, db_index=True)

    comments = generic.GenericRelation(ChangesetComment,
                                       content_type_field='content_type',
                                       object_id_field='revision_id')

    created = models.DateTimeField(auto_now_add=True, db_index=True)
    modified = models.DateTimeField(auto_now=True, db_index=True)

    is_changed = False

    @property
    def source(self):
        """
        The thing of which this is a revision.
        Since this is different for each revision,
        the subclass must override this.
        """
        # Call separate method for polymorphism
        return self._get_source()

    def _get_source(self):
        raise NotImplementedError

    @property
    def source_name(self):
        """
        Used to key lookups in various shared view methods.
        """
        # Call separate method for polymorphism
        return self._get_source_name()

    def _get_source_name(self):
        raise NotImplementedError

    def commit_to_display(self):
        """
        Writes the changes from the revision back to the display object.

        Revisions should handle their own dependencies on other revisions.
        """
        # TODO: Dependency mechanism.
        raise NotImplementedError


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


class PublisherRevisionManagerBase(RevisionManager):
    @classmethod
    def assignable_field_list(cls):
        # order exactly as desired in compare page
        return ['name',
                'year_began',
                'year_began_uncertain',
                'year_ended',
                'year_ended_uncertain',
                'url',
                'notes']

    def _base_field_kwargs(self, instance):
        kwargs = {f: getattr(instance, f)
                  for f in self.assignable_field_list()}
        kwargs['keywords'] = get_keywords(instance)
        return kwargs


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

    def _assign_base_fields(self, target):
        for field in PublisherRevisionManagerBase.assignable_field_list():
            setattr(target, field, getattr(self, field))
        target.save()
        save_keywords(self, target)

    @classmethod
    def form_field_list(cls):
        """
        Ordered list of fields that should appear in the edit form.
        """
        # NOTE: This replaces the old _field_list() method, but I'm
        #       not changing things in views.py and forms.py yet.

        # Keywords are last on the compare page, so we can just append.
        fields = list(PublisherRevisionManagerBase.assignable_field_list())
        fields.append('keywords')
        return fields


class PublisherRevisionManager(PublisherRevisionManagerBase):
    """
    Custom manager allowing the cloning of revisions from existing rows.
    """

    def clone_revision(self, publisher, changeset):
        """
        Create a new revision based on a Publisher instance.

        This new revision will be where the edits are made.
        Entirely new publishers should be started by simply instantiating
        a new PublisherRevision directly.
        """
        return PublisherRevisionManagerBase.clone_revision(
            self,
            instance=publisher,
            instance_class=Publisher,
            changeset=changeset)

    def _do_create_revision(self, publisher, changeset, **ignore):
        """
        Helper delegate to do the class-specific work of clone_revision.
        """
        kwargs = self._base_field_kwargs(publisher)

        revision = PublisherRevision(publisher=publisher,
                                     changeset=changeset,
                                     country=publisher.country,
                                     is_master=publisher.is_master,
                                     parent=publisher.parent,
                                     **kwargs)

        revision.save()
        return revision


class PublisherRevision(PublisherRevisionBase):
    class Meta:
        db_table = 'oi_publisher_revision'
        ordering = ['-created', '-id']

    objects = PublisherRevisionManager()

    publisher = models.ForeignKey('gcd.Publisher', null=True,
                                  related_name='revisions')

    country = models.ForeignKey('gcd.Country', db_index=True)

    # Deprecated fields about relating publishers/imprints to each other
    is_master = models.BooleanField(default=True, db_index=True)
    parent = models.ForeignKey('gcd.Publisher', default=None,
                               null=True, blank=True, db_index=True,
                               related_name='imprint_revisions')

    date_inferred = models.BooleanField(default=False)

    def _get_source(self):
        return self.publisher

    def _get_source_name(self):
        return 'publisher'

    @classmethod
    def form_field_list(cls):
        fields = super(PublisherRevision, cls).form_field_list()
        fields.insert(fields.index('url'), 'country')
        fields.extend(('is_master', 'parent'))
        return fields

    def commit_to_display(self, clear_reservation=True):
        pub = self.publisher
        if pub is None:
            pub = Publisher(imprint_count=0,
                            series_count=0,
                            issue_count=0)
            update_count('publishers', 1, country=self.country)
        elif self.deleted:
            update_count('publishers', -1, country=pub.country)
            pub.delete()
            return

        pub.country = self.country
        pub.is_master = self.is_master
        pub.parent = self.parent
        self._assign_base_fields(pub)

        if clear_reservation:
            pub.reserved = False

        pub.save()
        if self.publisher is None:
            self.publisher = pub
            self.save()


class IndiciaPublisherRevisionManager(PublisherRevisionManagerBase):

    def clone_revision(self, indicia_publisher, changeset):
        """
        Create a new revision based on an IndiciaPublisher instance.

        This new revision will be where the edits are made.
        Entirely new publishers should be started by simply instantiating
        a new IndiciaPublisherRevision directly.
        """
        return PublisherRevisionManagerBase.clone_revision(
            self,
            instance=indicia_publisher,
            instance_class=IndiciaPublisher,
            changeset=changeset)

    def _do_create_revision(self, indicia_publisher, changeset, **ignore):
        """
        Helper delegate to do the class-specific work of clone_revision.
        """
        kwargs = self._base_field_kwargs(indicia_publisher)

        revision = IndiciaPublisherRevision(
            indicia_publisher=indicia_publisher,
            changeset=changeset,
            is_surrogate=indicia_publisher.is_surrogate,
            country=indicia_publisher.country,
            parent=indicia_publisher.parent,
            **kwargs)

        revision.save()
        return revision


class IndiciaPublisherRevision(PublisherRevisionBase):
    class Meta:
        db_table = 'oi_indicia_publisher_revision'
        ordering = ['-created', '-id']

    objects = IndiciaPublisherRevisionManager()

    indicia_publisher = models.ForeignKey('gcd.IndiciaPublisher', null=True,
                                          related_name='revisions')

    is_surrogate = models.BooleanField(default=False)

    country = models.ForeignKey('gcd.Country', db_index=True,
                                related_name='indicia_publishers_revisions')

    parent = models.ForeignKey('gcd.Publisher',
                               null=True, blank=True, db_index=True,
                               related_name='indicia_publisher_revisions')

    def _get_source(self):
        return self.indicia_publisher

    def _get_source_name(self):
        return 'indicia_publisher'

    def _do_complete_added_revision(self, parent):
        """
        Do the necessary processing to complete the fields of a new
        series revision for adding a record before it can be saved.
        """
        self.parent = parent

    def commit_to_display(self, clear_reservation=True):
        ipub = self.indicia_publisher
        if ipub is None:
            ipub = IndiciaPublisher()
            self.parent.indicia_publisher_count = \
                F('indicia_publisher_count') + 1
            self.parent.save()
            update_count('indicia publishers', 1, country=self.country)

        elif self.deleted:
            self.parent.indicia_publisher_count = \
                F('indicia_publisher_count') - 1
            self.parent.save()
            update_count('indicia publishers', -1, country=ipub.country)
            ipub.delete()
            return

        ipub.is_surrogate = self.is_surrogate
        ipub.country = self.country
        ipub.parent = self.parent
        self._assign_base_fields(ipub)

        if clear_reservation:
            ipub.reserved = False

        ipub.save()
        if self.indicia_publisher is None:
            self.indicia_publisher = ipub
            self.save()


class BrandGroupRevisionManager(PublisherRevisionManagerBase):

    def clone_revision(self, brand_group, changeset):
        """
        Create a new revision based on a BrandGroup instance.

        This new revision will be where the edits are made.
        Entirely new publishers should be started by simply instantiating
        a new BrandGroupRevision directly.
        """
        return PublisherRevisionManagerBase.clone_revision(
            self,
            instance=brand_group,
            instance_class=BrandGroup,
            changeset=changeset)

    def _do_create_revision(self, brand_group, changeset, **ignore):
        """
        Helper delegate to do the class-specific work of clone_revision.
        """
        kwargs = self._base_field_kwargs(brand_group)

        revision = BrandGroupRevision(brand_group=brand_group,
                                      changeset=changeset,
                                      parent=brand_group.parent,
                                      **kwargs)

        revision.save()
        return revision


class BrandGroupRevision(PublisherRevisionBase):
    class Meta:
        db_table = 'oi_brand_group_revision'
        ordering = ['-created', '-id']

    objects = BrandGroupRevisionManager()

    brand_group = models.ForeignKey('gcd.BrandGroup', null=True,
                                    related_name='revisions')

    parent = models.ForeignKey('gcd.Publisher',
                               null=True, blank=True, db_index=True,
                               related_name='brand_group_revisions')

    def _get_source(self):
        return self.brand_group

    def _get_source_name(self):
        return 'brand_group'

    def _do_complete_added_revision(self, parent):
        """
        Do the necessary processing to complete the fields of a new
        series revision for adding a record before it can be saved.
        """
        self.parent = parent

    def commit_to_display(self, clear_reservation=True):
        brand_group = self.brand_group
        # TODO global stats for brand groups ?
        if brand_group is None:
            brand_group = BrandGroup()
            self.parent.brand_count = F('brand_count') + 1
            self.parent.save()

        elif self.deleted:
            self.parent.brand_count = F('brand_count') - 1
            self.parent.save()
            brand_group.delete()
            return

        brand_group.parent = self.parent
        self._assign_base_fields(brand_group)

        if clear_reservation:
            brand_group.reserved = False

        brand_group.save()
        if self.brand_group is None:
            self.brand_group = brand_group
            self.save()
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


class BrandRevisionManager(PublisherRevisionManagerBase):

    def clone_revision(self, brand, changeset):
        """
        Given an existing Brand instance, create a new revision based on it.

        This new revision will be where the edits are made.
        Entirely new brands should be started by simply instantiating
        a new BrandRevision directly.
        """
        return PublisherRevisionManagerBase.clone_revision(
            self,
            instance=brand,
            instance_class=Brand,
            changeset=changeset)

    def _do_create_revision(self, brand, changeset, **ignore):
        """
        Helper delegate to do the class-specific work of clone_revision.
        """
        kwargs = self._base_field_kwargs(brand)

        revision = BrandRevision(brand=brand, changeset=changeset, **kwargs)

        revision.save()
        if brand.group.count():
            revision.group.add(*list(brand.group.all().values_list('id',
                                                                   flat=True)))
        return revision


class BrandRevision(PublisherRevisionBase):
    class Meta:
        db_table = 'oi_brand_revision'
        ordering = ['-created', '-id']

    objects = BrandRevisionManager()

    brand = models.ForeignKey('gcd.Brand', null=True, related_name='revisions')
    # parent needs to be kept for old revisions
    parent = models.ForeignKey('gcd.Publisher',
                               null=True, blank=True, db_index=True,
                               related_name='brand_revisions')
    group = models.ManyToManyField('gcd.BrandGroup', blank=False,
                                   related_name='brand_revisions')

    def _get_source(self):
        return self.brand

    def _get_source_name(self):
        return 'brand'

    def commit_to_display(self, clear_reservation=True):
        brand = self.brand
        if brand is None:
            brand = Brand()
            update_count('brands', 1)

        elif self.deleted:
            update_count('brands', -1)
            brand.delete()
            return

        brand.parent = self.parent
        self._assign_base_fields(brand)

        if clear_reservation:
            brand.reserved = False

        brand_groups = brand.group.all().values_list('id', flat=True)
        revision_groups = self.group.all().values_list('id', flat=True)
        if set(brand_groups) != set(revision_groups):
            for group in brand.group.all():
                if group.id not in revision_groups:
                    group.issue_count = F('issue_count') - self.issue_count
                group.save()
            for group in self.group.all():
                if group.id not in brand_groups:
                    group.issue_count = F('issue_count') + self.issue_count
                group.save()

        brand.save()
        brand.group.clear()
        if self.group.count():
            brand.group.add(*list(self.group.all().values_list('id',
                                                               flat=True)))
        if self.brand is None:
            self.brand = brand
            self.save()

            if brand.group.count() != 1:
                raise NotImplementedError

            group = brand.group.get()
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


class BrandUseRevisionManager(RevisionManager):

    def clone_revision(self, brand_use, changeset):
        """
        Given an existing BrandUse instance, create a new revision based on it.

        This new revision will be where the edits are made.
        Entirely new publishers should be started by simply instantiating
        a new BrandUseRevision directly.
        """
        return RevisionManager.clone_revision(self,
                                              instance=brand_use,
                                              instance_class=BrandUse,
                                              changeset=changeset)

    def _do_create_revision(self, brand_use, changeset, **ignore):
        """
        Helper delegate to do the class-specific work of clone_revision.
        """
        revision = BrandUseRevision(
            # revision-specific fields:
            brand_use=brand_use,
            changeset=changeset,

            # copied fields:
            emblem=brand_use.emblem,
            publisher=brand_use.publisher,
            year_began=brand_use.year_began,
            year_ended=brand_use.year_ended,
            year_began_uncertain=brand_use.year_began_uncertain,
            year_ended_uncertain=brand_use.year_ended_uncertain,
            notes=brand_use.notes)

        revision.save()
        return revision


def get_brand_use_field_list():
    return ['year_began', 'year_began_uncertain',
            'year_ended', 'year_ended_uncertain', 'notes']


class BrandUseRevision(Revision):
    class Meta:
        db_table = 'oi_brand_use_revision'
        ordering = ['-created', '-id']

    objects = BrandUseRevisionManager()

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

    def _get_source(self):
        return self.brand_use

    def _get_source_name(self):
        return 'brand_use'

    def _do_complete_added_revision(self, emblem, publisher):
        """
        Do the necessary processing to complete the fields of a new
        BrandUse revision for adding a record before it can be saved.
        """
        self.publisher = publisher
        self.emblem = emblem

    def commit_to_display(self, clear_reservation=True):
        brand_use = self.brand_use
        if brand_use is None:
            brand_use = BrandUse()
            brand_use.emblem = self.emblem
        elif self.deleted:
            brand_use = self.brand_use
            for revision in brand_use.revisions.all():
                setattr(revision, 'brand_use', None)
                revision.save()
            brand_use.delete()
            return

        brand_use.publisher = self.publisher
        brand_use.year_began = self.year_began
        brand_use.year_ended = self.year_ended
        brand_use.year_began_uncertain = self.year_began_uncertain
        brand_use.year_ended_uncertain = self.year_ended_uncertain
        brand_use.notes = self.notes

        if clear_reservation:
            brand_use.reserved = False

        brand_use.save()
        if self.brand_use is None:
            self.brand_use = brand_use
            self.save()


class CoverRevisionManager(RevisionManager):
    """
    Custom manager allowing the cloning of revisions from existing rows.
    """

    def clone_revision(self, cover, changeset):
        """
        Given an existing Cover instance, create a new revision based on it.

        This new revision will be where the replacement is stored.
        """
        return RevisionManager.clone_revision(self,
                                              instance=cover,
                                              instance_class=Cover,
                                              changeset=changeset)

    def _do_create_revision(self, cover, changeset, **ignore):
        """
        Helper delegate to do the class-specific work of clone_revision.
        """
        revision = CoverRevision(
            # revision-specific fields:
            cover=cover,
            changeset=changeset,

            # copied fields:
            issue=cover.issue)

        revision.save()
        return revision


class CoverRevision(Revision):
    class Meta:
        db_table = 'oi_cover_revision'
        ordering = ['-created', '-id']

    objects = CoverRevisionManager()

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

    def _get_source(self):
        return self.cover

    def _get_source_name(self):
        return 'cover'

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


class SeriesRevisionManager(RevisionManager):
    """
    Custom manager allowing the cloning of revisions from existing rows.
    """

    def clone_revision(self, series, changeset):
        """
        Given an existing Series instance, create a new revision based on it.

        This new revision will be where the edits are made.
        If there are no revisions, first save a baseline so that the pre-edit
        values are preserved.
        Entirely new series should be started by simply instantiating
        a new SeriesRevision directly.
        """
        return RevisionManager.clone_revision(self,
                                              instance=series,
                                              instance_class=Series,
                                              changeset=changeset)

    def _do_create_revision(self, series, changeset, **ignore):
        """
        Helper delegate to do the class-specific work of clone_revision.
        """
        revision = SeriesRevision(
            # revision-specific fields:
            series=series,
            changeset=changeset,

            # copied fields:
            name=series.name,
            leading_article=series.name != series.sort_name,
            format=series.format,
            color=series.color,
            dimensions=series.dimensions,
            paper_stock=series.paper_stock,
            binding=series.binding,
            publishing_format=series.publishing_format,
            publication_type=series.publication_type,
            is_singleton=series.is_singleton,
            notes=series.notes,
            keywords=get_keywords(series),
            year_began=series.year_began,
            year_ended=series.year_ended,
            year_began_uncertain=series.year_began_uncertain,
            year_ended_uncertain=series.year_ended_uncertain,
            is_current=series.is_current,

            publication_notes=series.publication_notes,
            tracking_notes=series.tracking_notes,

            has_barcode=series.has_barcode,
            has_indicia_frequency=series.has_indicia_frequency,
            has_isbn=series.has_isbn,
            has_volume=series.has_volume,
            has_issue_title=series.has_issue_title,
            has_rating=series.has_rating,
            is_comics_publication=series.is_comics_publication,

            country=series.country,
            language=series.language,
            publisher=series.publisher)

        revision.save()
        return revision


def get_series_field_list():
    return ['name', 'leading_article', 'imprint', 'format', 'color',
            'dimensions', 'paper_stock', 'binding', 'publishing_format',
            'publication_type', 'is_singleton', 'year_began',
            'year_began_uncertain', 'year_ended', 'year_ended_uncertain',
            'is_current', 'country', 'language', 'has_barcode',
            'has_indicia_frequency', 'has_isbn', 'has_issue_title',
            'has_volume', 'has_rating', 'is_comics_publication',
            'tracking_notes', 'notes', 'keywords']


class SeriesRevision(Revision):
    class Meta:
        db_table = 'oi_series_revision'
        ordering = ['-created', '-id']

    objects = SeriesRevisionManager()

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

    def _get_source(self):
        return self.series

    def _get_source_name(self):
        return 'series'

    @classmethod
    def form_field_list(cls):
        # TODO: The old _field_list() method has an instance check
        #       having to do with a changed publisher.  I'm not quite
        #       ready to give up on this being a classmethod, but
        #       obviously that needs to be addressed.
        return get_series_field_list() + [u'publication_notes']

    def _do_complete_added_revision(self, publisher):
        """
        Do the necessary processing to complete the fields of a new
        series revision for adding a record before it can be saved.
        """
        self.publisher = publisher

    def commit_to_display(self, clear_reservation=True):
        series = self.series
        if series is None:
            series = Series(issue_count=0)
            if self.is_comics_publication:
                self.publisher.series_count = F('series_count') + 1
                if not self.is_singleton:
                    # if save also happens in IssueRevision gets twice +1
                    self.publisher.save()
                update_count('series', 1, language=self.language,
                             country=self.country)
            if self.is_singleton:
                issue_revision = IssueRevision(
                    changeset=self.changeset,
                    after=None,
                    number='[nn]',
                    publication_date=self.year_began)
                if len(unicode(self.year_began)) == 4:
                    issue_revision.key_date = '%d-00-00' % self.year_began

        elif self.deleted:
            if series.is_comics_publication:
                self.publisher.series_count = F('series_count') - 1
                # TODO: implement when/if we allow series deletions along
                # with all their issues
                # self.publisher.issue_count -= series.issue_count
                self.publisher.save()
            series.delete()
            if series.is_comics_publication:
                update_count('series', -1, language=series.language,
                             country=series.country)
            reservation = self.source.get_ongoing_reservation()
            if reservation:
                reservation.delete()
            return
        else:
            if self.publisher != self.series.publisher and \
               series.is_comics_publication:
                self.publisher.issue_count = (F('issue_count') +
                                              series.issue_count)
                self.publisher.series_count = F('series_count') + 1
                self.publisher.save()
                self.series.publisher.issue_count = (F('issue_count') -
                                                     series.issue_count)
                self.series.publisher.series_count = F('series_count') - 1
                self.series.publisher.save()

        series.name = self.name
        if self.leading_article:
            series.sort_name = remove_leading_article(self.name)
        else:
            series.sort_name = self.name
        series.format = self.format
        series.color = self.color
        series.dimensions = self.dimensions
        series.paper_stock = self.paper_stock
        series.binding = self.binding
        series.publishing_format = self.publishing_format
        series.notes = self.notes
        series.is_singleton = self.is_singleton
        series.publication_type = self.publication_type

        series.year_began = self.year_began
        series.year_ended = self.year_ended
        series.year_began_uncertain = self.year_began_uncertain
        series.year_ended_uncertain = self.year_ended_uncertain
        series.is_current = self.is_current
        series.has_barcode = self.has_barcode
        series.has_indicia_frequency = self.has_indicia_frequency
        series.has_isbn = self.has_isbn
        series.has_issue_title = self.has_issue_title
        series.has_volume = self.has_volume
        series.has_rating = self.has_rating

        reservation = series.get_ongoing_reservation()
        if (not self.is_current and
                reservation and
                self.previous() and self.previous().is_current):
            reservation.delete()

        series.publication_notes = self.publication_notes
        series.tracking_notes = self.tracking_notes

        # a new series has language_id None
        if series.language_id is None:
            if series.issue_count:
                raise NotImplementedError("New series can't have issues!")

        else:
            if series.is_comics_publication != self.is_comics_publication:
                if series.is_comics_publication:
                    count = -1
                else:
                    count = +1
                update_count('series', count, language=series.language,
                             country=series.country)
                if series.issue_count:
                    update_count('issues', count*series.issue_count,
                                 language=series.language,
                                 country=series.country)
                variant_issues = Issue.objects \
                    .filter(series=series, deleted=False) \
                    .exclude(variant_of=None)\
                    .count()
                update_count('variant issues', count*variant_issues,
                             language=series.language, country=series.country)
                issue_indexes = Issue.objects \
                    .filter(series=series, deleted=False) \
                    .exclude(is_indexed=INDEXED['skeleton']) \
                    .count()
                update_count('issue indexes', count*issue_indexes,
                             language=series.language, country=series.country)

            if ((series.language != self.language or
                 series.country != self.country) and
                    self.is_comics_publication):
                update_count('series', -1,
                             language=series.language,
                             country=series.country)
                update_count('series', 1,
                             language=self.language,
                             country=self.country)
                if series.issue_count:
                    update_count('issues', -series.issue_count,
                                 language=series.language,
                                 country=series.country)
                    update_count('issues', series.issue_count,
                                 language=self.language,
                                 country=self.country)
                    variant_issues = Issue.objects \
                        .filter(series=series, deleted=False) \
                        .exclude(variant_of=None) \
                        .count()
                    update_count('variant issues', -variant_issues,
                                 language=series.language,
                                 country=series.country)
                    update_count('variant issues', variant_issues,
                                 language=self.language,
                                 country=self.country)
                    issue_indexes = \
                        Issue.objects.filter(series=series, deleted=False) \
                                     .exclude(is_indexed=INDEXED['skeleton']) \
                                     .count()
                    update_count('issue indexes', -issue_indexes,
                                 language=series.language,
                                 country=series.country)
                    update_count('issue indexes', issue_indexes,
                                 language=self.language,
                                 country=self.country)
                    story_count = Story.objects \
                                       .filter(issue__series=series,
                                               deleted=False) \
                                       .count()
                    update_count('stories', -story_count,
                                 language=series.language,
                                 country=series.country)
                    update_count('stories', story_count,
                                 language=self.language,
                                 country=self.country)
                    update_count('covers', -series.scan_count(),
                                 language=series.language,
                                 country=series.country)
                    update_count('covers', series.scan_count(),
                                 language=self.language, country=self.country)
        series.country = self.country
        series.language = self.language
        series.publisher = self.publisher
        if series.is_comics_publication != self.is_comics_publication:
            series.has_gallery = (self.is_comics_publication and
                                  series.scan_count())
        series.is_comics_publication = self.is_comics_publication

        if clear_reservation:
            series.reserved = False

        series.save()
        save_keywords(self, series)
        series.save()
        if self.series is None:
            self.series = series
            self.save()
            if self.is_singleton:
                issue_revision.series = series
                issue_revision.save()
                issue_revision.commit_to_display()


class SeriesBondRevisionManager(RevisionManager):

    def clone_revision(self, series_bond, changeset):
        """
        Create a new revision based on a SeriesBond instance.

        This new revision will be where the edits are made.
        """
        return RevisionManager.clone_revision(self,
                                              instance=series_bond,
                                              instance_class=SeriesBond,
                                              changeset=changeset)

    def _do_create_revision(self, series_bond, changeset):
        """
        Helper delegate to do the class-specific work of clone_revision.
        """
        revision = SeriesBondRevision(
            # revision-specific fields:
            series_bond=series_bond,
            changeset=changeset,

            # copied fields:
            origin=series_bond.origin,
            origin_issue=series_bond.origin_issue,
            target=series_bond.target,
            target_issue=series_bond.target_issue,
            bond_type=series_bond.bond_type,
            notes=series_bond.notes)

        revision.save()
        previous_revision = SeriesBondRevision.objects.get(
            series_bond=series_bond,
            next_revision=None,
            changeset__state=states.APPROVED)
        revision.previous_revision = previous_revision
        revision.save()
        return revision


def get_series_bond_field_list():
    return ['bond_type', 'notes']


class SeriesBondRevision(Revision):
    class Meta:
        db_table = 'oi_series_bond_revision'
        ordering = ['-created', '-id']
        get_latest_by = "created"

    objects = SeriesBondRevisionManager()

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

    previous_revision = models.OneToOneField('self', null=True,
                                             related_name='next_revision')

    def _get_source(self):
        return self.series_bond

    def _get_source_name(self):
        return 'series_bond'

    def commit_to_display(self, clear_reservation=True):
        series_bond = self.series_bond
        if self.deleted:
            for revision in series_bond.revisions.all():
                setattr(revision, "series_bond_id", None)
                revision.save()
            series_bond.delete()
            return

        if series_bond is None:
            series_bond = SeriesBond()
        series_bond.origin = self.origin
        series_bond.origin_issue = self.origin_issue
        series_bond.target = self.target
        series_bond.target_issue = self.target_issue
        series_bond.notes = self.notes
        series_bond.bond_type = self.bond_type

        if clear_reservation:
            series_bond.reserved = False

        series_bond.save()
        if self.series_bond is None:
            self.series_bond = series_bond
            self.save()


class IssueRevisionManager(RevisionManager):

    def clone_revision(self, issue, changeset):
        """
        Given an existing Issue instance, create a new revision based on it.

        This new revision will be where the edits are made.
        If there are no revisions, first save a baseline so that the pre-edit
        values are preserved.
        Entirely new issues should be started by simply instantiating
        a new IssueRevision directly.
        """
        return RevisionManager.clone_revision(self,
                                              instance=issue,
                                              instance_class=Issue,
                                              changeset=changeset)

    def _do_create_revision(self, issue, changeset, **ignore):
        """
        Helper delegate to do the class-specific work of clone_revision.
        """
        revision = IssueRevision(
            # revision-specific fields:
            issue=issue,
            changeset=changeset,

            # copied fields:
            number=issue.number,
            title=issue.title,
            no_title=issue.no_title,
            volume=issue.volume,
            no_volume=issue.no_volume,
            display_volume_with_number=issue.display_volume_with_number,
            publication_date=issue.publication_date,
            key_date=issue.key_date,
            on_sale_date_uncertain=issue.on_sale_date_uncertain,
            price=issue.price,
            indicia_frequency=issue.indicia_frequency,
            no_indicia_frequency=issue.no_indicia_frequency,
            series=issue.series,
            indicia_publisher=issue.indicia_publisher,
            indicia_pub_not_printed=issue.indicia_pub_not_printed,
            brand=issue.brand,
            no_brand=issue.no_brand,
            page_count=issue.page_count,
            page_count_uncertain=issue.page_count_uncertain,
            editing=issue.editing,
            no_editing=issue.no_editing,
            barcode=issue.barcode,
            no_barcode=issue.no_barcode,
            isbn=issue.isbn,
            no_isbn=issue.no_isbn,
            variant_of=issue.variant_of,
            variant_name=issue.variant_name,
            rating=issue.rating,
            no_rating=issue.no_rating,
            notes=issue.notes,
            keywords=get_keywords(issue))

        if issue.on_sale_date:
            (revision.year_on_sale,
             revision.month_on_sale,
             revision.day_on_sale) = on_sale_date_fields(issue.on_sale_date)

        revision.save()
        return revision


def get_issue_field_list():
    return ['number', 'title', 'no_title',
            'volume', 'no_volume', 'display_volume_with_number',
            'indicia_publisher', 'indicia_pub_not_printed',
            'brand', 'no_brand', 'publication_date', 'year_on_sale',
            'month_on_sale', 'day_on_sale', 'on_sale_date_uncertain',
            'key_date', 'indicia_frequency', 'no_indicia_frequency', 'price',
            'page_count', 'page_count_uncertain', 'editing', 'no_editing',
            'isbn', 'no_isbn', 'barcode', 'no_barcode', 'rating', 'no_rating',
            'notes', 'keywords']


class IssueRevision(Revision):
    class Meta:
        db_table = 'oi_issue_revision'
        ordering = ['-created', '-id']

    objects = IssueRevisionManager()

    issue = models.ForeignKey(Issue, null=True, related_name='revisions')

    # If not null, insert or move the issue after the given issue
    # when saving back the the DB. If null, place at the beginning of
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

    def _get_source(self):
        return self.issue

    def _get_source_name(self):
        return 'issue'

    def _do_complete_added_revision(self, series, variant_of=None):
        """
        Do the necessary processing to complete the fields of a new
        issue revision for adding a record before it can be saved.
        """
        self.series = series
        if variant_of:
            self.variant_of = variant_of

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


def get_story_field_list():
    return ['sequence_number', 'title', 'title_inferred', 'type',
            'feature', 'genre', 'job_number',
            'script', 'no_script', 'pencils', 'no_pencils', 'inks',
            'no_inks', 'colors', 'no_colors', 'letters', 'no_letters',
            'editing', 'no_editing', 'page_count', 'page_count_uncertain',
            'characters', 'synopsis', 'reprint_notes', 'notes', 'keywords']


class StoryRevisionManager(RevisionManager):

    def clone_revision(self, story, changeset):
        """
        Given an existing Story instance, create a new revision based on it.

        This new revision will be where the edits are made.
        If there are no revisions, first save a baseline so that the pre-edit
        values are preserved.
        Entirely new stories should be started by simply instantiating
        a new StoryRevision directly.
        """
        return RevisionManager.clone_revision(self,
                                              instance=story,
                                              instance_class=Story,
                                              changeset=changeset)

    def _do_create_revision(self, story, changeset, **ignore):
        """
        Helper delegate to do the class-specific work of clone_revision.
        """
        revision = StoryRevision(
            # revision-specific fields:
            story=story,
            changeset=changeset,

            # copied fields:
            title=story.title,
            title_inferred=story.title_inferred,
            feature=story.feature,
            page_count=story.page_count,
            page_count_uncertain=story.page_count_uncertain,

            script=story.script,
            pencils=story.pencils,
            inks=story.inks,
            colors=story.colors,
            letters=story.letters,
            editing=story.editing,

            no_script=story.no_script,
            no_pencils=story.no_pencils,
            no_inks=story.no_inks,
            no_colors=story.no_colors,
            no_letters=story.no_letters,
            no_editing=story.no_editing,

            notes=story.notes,
            keywords=get_keywords(story),
            synopsis=story.synopsis,
            characters=story.characters,
            reprint_notes=story.reprint_notes,
            genre=story.genre,
            type=story.type,
            job_number=story.job_number,
            sequence_number=story.sequence_number,

            issue=story.issue)

        revision.save()
        return revision


class StoryRevision(Revision):
    class Meta:
        db_table = 'oi_story_revision'
        ordering = ['-created', '-id']

    objects = StoryRevisionManager()

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

    def _get_source(self):
        return self.story

    def _get_source_name(self):
        return 'story'

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

    def clone_revision(self, reprint, changeset):
        """
        Given an existing Reprint instance, create a new revision based on it.

        This new revision will be where the edits are made.
        """
        return RevisionManager.clone_revision(self,
                                              instance=reprint,
                                              instance_class=type(reprint),
                                              changeset=changeset)

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

    previous_revision = models.OneToOneField('self', null=True,
                                             related_name='next_revision')

    def _get_source(self):
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

    def _get_source_name(self):
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


class ImageRevisionManager(RevisionManager):

    def clone_revision(self, image, changeset):
        """
        Given an existing Image instance, create a new revision based on it.

        This new revision will be where the replacement is stored.
        """
        return RevisionManager.clone_revision(self,
                                              instance=image,
                                              instance_class=Image,
                                              changeset=changeset)

    def _do_create_revision(self, image, changeset, **ignore):
        """
        Helper delegate to do the class-specific work of clone_revision.
        """
        revision = ImageRevision(
            # revision-specific fields:
            image=image,
            changeset=changeset,

            # copied fields:
            content_type=image.content_type,
            object_id=image.object_id,
            type=image.type)

        revision.save()
        return revision


class ImageRevision(Revision):
    class Meta:
        db_table = 'oi_image_revision'
        ordering = ['created']

    objects = ImageRevisionManager()

    image = models.ForeignKey(Image, null=True, related_name='revisions')

    content_type = models.ForeignKey(content_models.ContentType, null=True)
    object_id = models.PositiveIntegerField(db_index=True, null=True)
    object = generic.GenericForeignKey('content_type', 'object_id')

    type = models.ForeignKey(ImageType)

    image_file = models.ImageField(upload_to='%s/%%m_%%Y' %
                                             settings.NEW_GENERIC_IMAGE_DIR)
    scaled_image = ImageSpecField([ResizeToFit(width=400)],
                                  image_field='image_file',
                                  format='JPEG', options={'quality': 90})

    marked = models.BooleanField(default=False)
    is_replacement = models.BooleanField(default=False)

    def _get_source(self):
        return self.image

    def _get_source_name(self):
        return 'image'

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
