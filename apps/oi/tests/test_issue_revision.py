# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import mock
import pytest

from django.db import models

from apps.gcd.models import Series, Issue, INDEXED
from apps.oi.models import Changeset, Revision, IssueRevision

RECENT = 'apps.gcd.models.recent.RecentIndexedIssue.objects.update_recents'
ACTION = 'apps.oi.models.Changeset.changeset_action'
CSET = 'apps.oi.models.Changeset'
IREV = 'apps.oi.models.IssueRevision'


def test_excluded_fields():
    assert IssueRevision._get_excluded_field_names() == \
        Revision._get_excluded_field_names()


def test_classification():
    meta = Issue._meta
    gf = meta.get_field
    regular_fields = {
        'number': gf('number'),
        'title': gf('title'),
        'no_title': gf('no_title'),
        'volume': gf('volume'),
        'no_volume': gf('no_volume'),
        'display_volume_with_number': gf('display_volume_with_number'),
        'variant_of': gf('variant_of'),
        'variant_name': gf('variant_name'),
        'isbn': gf('isbn'),
        'no_isbn': gf('no_isbn'),
        'barcode': gf('barcode'),
        'no_barcode': gf('no_barcode'),
        'rating': gf('rating'),
        'no_rating': gf('no_rating'),
        'publication_date': gf('publication_date'),
        'key_date': gf('key_date'),
        'on_sale_date_uncertain': gf('on_sale_date_uncertain'),
        'indicia_frequency': gf('indicia_frequency'),
        'no_indicia_frequency': gf('no_indicia_frequency'),
        'price': gf('price'),
        'page_count': gf('page_count'),
        'page_count_uncertain': gf('page_count_uncertain'),
        'editing': gf('editing'),
        'no_editing': gf('no_editing'),
        'notes': gf('notes'),
        'keywords': gf('keywords'),
        'series': gf('series'),
        'indicia_publisher': gf('indicia_publisher'),
        'indicia_pub_not_printed': gf('indicia_pub_not_printed'),
        'brand': gf('brand'),
        'no_brand': gf('no_brand'),
    }

    irregular_fields = {
        'valid_isbn': gf('valid_isbn'),
        'on_sale_date': gf('on_sale_date'),
        'sort_code': gf('sort_code'),
        'is_indexed': gf('is_indexed'),
    }

    assert IssueRevision._get_regular_fields() == regular_fields
    assert IssueRevision._get_irregular_fields() == irregular_fields

    single_value_fields = regular_fields.copy()
    del single_value_fields['keywords']
    assert IssueRevision._get_single_value_fields() == single_value_fields

    assert IssueRevision._get_multi_value_fields() == {}


def test_conditional_field_mapping():
    assert IssueRevision._get_conditional_field_tuple_mapping() == {
        'volume': ('series', 'has_volume'),
        'no_volume': ('series', 'has_volume'),
        'display_volume_with_issue': ('series', 'has_volume'),
        'title': ('series', 'has_issue_title'),
        'no_title': ('series', 'has_issue_title'),
        'barcode': ('series', 'has_barcode'),
        'no_barcode': ('series', 'has_barcode'),
        'isbn': ('series', 'has_isbn'),
        'no_isbn': ('series', 'has_isbn'),
        'valid_isbn': ('series', 'has_isbn'),
        'indicia_frequency': ('series', 'has_indicia_frequency'),
        'no_indicia_frequency': ('series', 'has_indicia_frequency'),
    }


def test_parent_field_tuples():
    assert IssueRevision._get_parent_field_tuples() == {
        ('series',),
        ('series', 'publisher'),
        ('brand', 'group'),
        ('brand',),
        ('indicia_publisher',),
    }


def test_stats_category_field_tuples():
    assert IssueRevision._get_stats_category_field_tuples() == {
        ('series', 'country'),
        ('series', 'language'),
    }


# Some parameter combinations are omitted because they make no sense.
@pytest.mark.parametrize('deleted, has_prev, changed',
                         [(False, False, False),
                          (False, True, True),
                          (False, True, False),
                          (True, True, False)])
def test_series_changed(deleted, has_prev, changed):
    s1 = Series(name='One')
    s2 = Series(name='Two') if changed else s1
    with mock.patch('%s.previous_revision' % IREV,
                    new_callable=mock.PropertyMock) as prev_mock:
        rev = IssueRevision(series=s2)
        rev.deleted = deleted
        if has_prev:
            prev_mock.return_value = IssueRevision(series=s1)
        else:
            prev_mock.return_value = None
        sc = rev.series_changed
        assert sc is changed


def test_pre_initial_save_with_date():
    rev = IssueRevision(issue=Issue(on_sale_date='2016-01-31'))
    rev._pre_initial_save()
    assert rev.year_on_sale == 2016
    assert rev.month_on_sale == 1
    assert rev.day_on_sale == 31


def test_pre_initial_save_no_date():
    rev = IssueRevision(issue=Issue())
    rev._pre_initial_save()
    assert rev.year_on_sale is None
    assert rev.month_on_sale is None
    assert rev.day_on_sale is None


@pytest.yield_fixture
def pre_commit_rev():
    with mock.patch('%s._same_series_revisions' % IREV), \
            mock.patch('%s._same_series_open_with_after' % IREV):
        s = Series(name='Some Series')
        i = Issue(number='1', series=s)
        rev = IssueRevision(
            changeset=Changeset(),
            issue=i,
            series=s,
            previous_revision=IssueRevision(changeset=Changeset(), issue=i))
        yield rev


def test_pre_commit_check_success(pre_commit_rev):
    pre_commit_rev._same_series_revisions.return_value \
                  .filter.return_value \
                  .exists.return_value = False
    pre_commit_rev._same_series_open_with_after.return_value \
                  .count.return_value = 1

    first_rev_mock = mock.MagicMock(spec=IssueRevision)

    pre_commit_rev._same_series_open_with_after.return_value \
                  .first.return_value = first_rev_mock
    pre_commit_rev._same_series_revisions.return_value \
                  .order_by.return_value \
                  .first.return_value = first_rev_mock

    pre_commit_rev._pre_commit_check()

    # Since we cover all of the main calls here, these aren't
    # checked in any of the exception-raising cases.
    pre_commit_rev._same_series_revisions.assert_has_calls([
        mock.call(),
        mock.call().filter(committed=True),
        mock.call().filter().exists(),
        mock.call(),
        mock.call().order_by('revision_sort_code'),
        mock.call().order_by().first()])

    # Note that the __nonzero__ call represents the result of exists()
    # being evaluated in a boolean expression.  __nonzero__ is the method
    # used to evaluate truthiness.  I wouldn't bother to check for it
    # but the only options are to include it, or to make the assertion
    # order-insensitive which is too loose of a check.
    pre_commit_rev._same_series_open_with_after.assert_has_calls([
        mock.call(),
        mock.call().count(),
        mock.call().exists(),
        mock.call().exists().__nonzero__(),
        mock.call().first()])


def test_pre_commit_check_already_checked(pre_commit_rev):
    pre_commit_rev._same_series_revisions.return_value \
                  .filter.return_value \
                  .exists.return_value = True

    pre_commit_rev._pre_commit_check()

    # This is the next thing we would call if we failed to bail out.
    assert not pre_commit_rev._same_series_open_with_after.called


def test_pre_commit_check_too_many_afters(pre_commit_rev):
    pre_commit_rev._same_series_revisions.return_value \
                  .filter.return_value \
                  .exists.return_value = False
    pre_commit_rev._same_series_open_with_after.return_value \
                  .count.return_value = 2
    with pytest.raises(ValueError) as excinfo:
        pre_commit_rev._pre_commit_check()

    assert ("Only one IssueRevision per series within a changeset can have "
            "'after' set.") in unicode(excinfo.value)


def test_pre_commit_check_after_not_first(pre_commit_rev):
    pre_commit_rev._same_series_revisions.return_value \
                  .filter.return_value \
                  .exists.return_value = False
    pre_commit_rev._same_series_open_with_after.return_value \
                  .count.return_value = 1

    after_rev_mock = mock.MagicMock(spec=IssueRevision)
    lowest_sort_mock = mock.MagicMock(spec=IssueRevision)

    pre_commit_rev._same_series_open_with_after.return_value \
                  .first.return_value = after_rev_mock
    pre_commit_rev._same_series_revisions.return_value \
                  .order_by.return_value \
                  .first.return_value = lowest_sort_mock

    with pytest.raises(ValueError) as excinfo:
        pre_commit_rev._pre_commit_check()

    assert ("The IssueRevision that specifies an 'after' must have "
            "the lowest revision_sort_code.") in unicode(excinfo.value)


@pytest.yield_fixture
def multiple_issue_revs():
    with mock.patch('apps.oi.models.Issue.objects') as obj_mock, \
            mock.patch('%s._same_series_revisions' % IREV) as same_mock, \
            mock.patch('%s._same_series_open_with_after' % IREV) as after_mock:

        same_mock.return_value.filter.return_value.exists.return_value = False

        s = Series(name='Some Series')
        # Issues already created, so they have sort codes.
        i1 = Issue(number='1', series=s, sort_code=0)
        i4 = Issue(number='4', series=s, sort_code=1)
        i5 = Issue(number='5', series=s, sort_code=2)
        i1.save = mock.MagicMock()
        i4.save = mock.MagicMock()
        i5.save = mock.MagicMock()

        # Issues being created, no sort codes yet.
        i2 = Issue(number='2', series=s)
        i3 = Issue(number='3', series=s)

        c = Changeset()
        rev2 = IssueRevision(changeset=c, issue=i2, series=s,
                             revision_sort_code=2)
        rev3 = IssueRevision(changeset=c, issue=i3, series=s,
                             revision_sort_code=3)

        yield ((i1, i2, i3, i4, i5), (rev2, rev3),
               after_mock, obj_mock, same_mock)


def _set_up_sort_code_query_sets(revision_list, later_issue_list,
                                 same_mock, obj_mock):

    # Use lambda with side effect to get a new iter() result each time.
    same_mock.return_value = mock.MagicMock(spec=models.QuerySet)
    same_mock.return_value.__iter__.side_effect = lambda: iter(revision_list)
    same_mock.return_value.count.return_value = len(revision_list)

    later_mock = mock.MagicMock(spec=models.QuerySet)
    later_mock.exists.return_value = bool(later_issue_list)
    later_mock.count.return_value = len(later_issue_list)
    try:
        later_mock.first.return_value = later_issue_list[0]
    except IndexError:
        later_mock.first.return_value = None
    later_mock.__iter__.side_effect = lambda: iter(later_issue_list)
    obj_mock.filter.return_value.order_by.return_value = later_mock


def test_ensure_sort_code_space_no_after(multiple_issue_revs):
    ((i1, i2, i3, i4, i5), (rev2, rev3),
     after_mock, obj_mock, same_mock) = multiple_issue_revs

    after_mock.return_value.first.return_value = None

    # With no "after" issue, we insert at the beginning, so i1 ends up
    # being a later issue in this test case.
    _set_up_sort_code_query_sets([rev2, rev3], [i1, i4, i5],
                                 same_mock, obj_mock)

    rev3._ensure_sort_code_space()

    assert i1.sort_code == 2
    i1.save.assert_called_once_with()
    assert i4.sort_code == 3
    i4.save.assert_called_once_with()
    assert i5.sort_code == 4
    i5.save.assert_called_once_with()


def test_ensure_sort_code_space_with_after(multiple_issue_revs):
    ((i1, i2, i3, i4, i5), (rev2, rev3),
     after_mock, obj_mock, same_mock) = multiple_issue_revs

    rev2.after = i1
    after_mock.return_value.first.return_value = rev2

    _set_up_sort_code_query_sets([rev2, rev3], [i4, i5], same_mock, obj_mock)

    rev3._ensure_sort_code_space()

    assert i1.sort_code == 0
    assert not i1.save.called

    assert i4.sort_code == 3
    i4.save.assert_called_once_with()
    assert i5.sort_code == 4
    i5.save.assert_called_once_with()


def test_ensure_sort_code_space_append_to_series(multiple_issue_revs):
    ((i1, i2, i3, i4, i5), (rev2, rev3),
     after_mock, obj_mock, same_mock) = multiple_issue_revs

    # In this case, we want an append so there are no later issues.
    _set_up_sort_code_query_sets([rev2, rev3], [], same_mock, obj_mock)

    # It shouldn't matter which rev we use because the values are all mocked,
    # Use rev2 because we use rev3 everywhere else.
    rev2._ensure_sort_code_space()

    # This would be the next method called, but we should return early instead.
    assert not same_mock.return_value.count.called


def test_ensure_sort_code_space_already_ensured(multiple_issue_revs):
    ((i1, i2, i3, i4, i5), (rev2, rev3),
     after_mock, obj_mock, same_mock) = multiple_issue_revs

    rev2.after = i1
    after_mock.return_value.first.return_value = rev2
    rev_list = [rev2, rev3]

    # Bump the sort codes up to where they would be if we've already
    # checked for this through another revision.
    # This test case is otherwise identical to the with_after test case.
    i4.sort_code = i4.sort_code + len(rev_list)
    i5.sort_code = i5.sort_code + len(rev_list)

    _set_up_sort_code_query_sets(rev_list, [i4, i5], same_mock, obj_mock)

    rev3._ensure_sort_code_space()

    # This is the for loop that we should skip and return early instead.
    assert (
        not obj_mock.filter.return_value.order_by.return_value.__iter__.called)


def test_pre_stats_measurement_non_move_edit():
    with mock.patch('%s.edited' % IREV,
                    new_callable=mock.PropertyMock) as edited_mock, \
            mock.patch('%s.series_changed' % IREV,
                       new_callable=mock.PropertyMock) as moved_mock, \
            mock.patch('%s._ensure_sort_code_space' % IREV) as sort_mock, \
            mock.patch('%s._open_prereq_revisions' % IREV) as open_mock:

        edited_mock.return_value = True
        moved_mock.return_value = False
        rev = IssueRevision(deleted=False)

        rev._pre_stats_measurement({})

        # We should have returned back out immediately, no further calls.
        assert not sort_mock.called
        assert not open_mock.called


@pytest.yield_fixture
def multiple_issue_revs_pre_stats(multiple_issue_revs):
    # While multiple_issue_revs has a few things the pre_stats_measurement
    # tests don't need, those things are harmless, and otherwise the
    # set-up is useful.
    (issues, revs, after_mock, obj_mock, same_mock) = multiple_issue_revs
    with mock.patch('%s.edited' % IREV,
                    new_callable=mock.PropertyMock) as edited_mock, \
            mock.patch('%s.series_changed' % IREV,
                       new_callable=mock.PropertyMock) as moved_mock, \
            mock.patch('%s._ensure_sort_code_space' % IREV) as sort_mock, \
            mock.patch('%s._open_prereq_revisions' % IREV) as open_mock:

        # We currenlty only use this fixture for added/deleted revisions.
        edited_mock.return_value = False
        moved_mock.return_value = False

        yield (issues, revs, after_mock, obj_mock, same_mock,
               sort_mock, open_mock)


def _set_up_prereqs(prereq_list_list, open_mock):
    last_all_mock = open_mock.return_value.all
    for prereq_list in prereq_list_list:
        mock_qs = mock.MagicMock(spec=models.QuerySet)
        mock_qs.count.return_value = len(prereq_list)
        try:
            mock_qs.first.return_value = prereq_list[0]
        except IndexError:
            mock_qs.first.return_value = None
        mock_qs.__iter__.side_effect = lambda: iter(prereq_list)

        # Just keep appending these to successive calls to all() as
        # we call all() each time through the loop to refresh.
        last_all_mock.return_value = mock_qs
        last_all_mock = last_all_mock.return_value.all


def test_pre_stats_measurement_added(multiple_issue_revs_pre_stats):
    ((i1, i2, i3, i4, i5), (rev2, rev3),
     after_mock, obj_mock, same_mock,
     sort_mock, open_mock) = multiple_issue_revs_pre_stats

    rev2.commit_to_display = mock.MagicMock()
    rev3.commit_to_display = mock.MagicMock()
    _set_up_prereqs([[rev2], []], open_mock)
    rev3._pre_stats_measurement({})

    sort_mock.assert_called_once_with()
    rev2.commit_to_display.assert_called_once_with()
    assert not rev3.commit_to_display.called


def test_pre_stats_measurement_exit_infinite_loop(
        multiple_issue_revs_pre_stats):
    ((i1, i2, i3, i4, i5), (rev2, rev3),
     after_mock, obj_mock, same_mock,
     sort_mock, open_mock) = multiple_issue_revs_pre_stats

    # Also check the special delete condition as it happens well before
    # the part where we test for the infinite loop.
    rev2.deleted = True
    rev3.deleted = True

    # Deletes work last to first for revs.
    _set_up_sort_code_query_sets([rev3, rev2], [i4, i5], same_mock, obj_mock)

    # Two trips through the loop should trigger the exception.
    # The prereq_list is the same both times, as the point is to exit
    # if we fail to reduce the list each time through the loop.
    rev3.commit_to_display = mock.MagicMock()
    prereq_list = [rev3]
    _set_up_prereqs([prereq_list, prereq_list], open_mock)

    # Now chain them up for successive calls to all().
    # mock_querysets[0].all.return_value = mock_querysets[1]
    # open_mock.return_value.all.return_value = mock_querysets[0]

    with pytest.raises(RuntimeError) as excinfo:
        # Deletes work last to first, so rev3 is a prereq of rev2.
        rev2._pre_stats_measurement({})

    assert "did not reduce" in unicode(excinfo.value)

    # As a delete, we should not have messed with sort_codes.
    assert not sort_mock.called
    rev3.commit_to_display.assert_called_once_with()


def test_post_commit_to_display():
    from apps.oi.models import ACTION_MODIFY

    with mock.patch(RECENT) as recent_mock, mock.patch(ACTION) as action_mock:
        action_mock.return_value = ACTION_MODIFY
        rev = IssueRevision(changeset=Changeset(),
                            issue=Issue(is_indexed=INDEXED['full']))

        rev._post_commit_to_display()

        recent_mock.assert_called_once_with(rev.issue)


def test_post_commit_to_display_not_a_modify():
    from apps.oi.models import ACTION_ADD

    with mock.patch(RECENT) as recent_mock, mock.patch(ACTION) as action_mock:
        action_mock.return_value = ACTION_ADD
        rev = IssueRevision(changeset=Changeset(),
                            issue=Issue(is_indexed=INDEXED['full']))

        rev._post_commit_to_display()

        assert not recent_mock.called


def test_post_commit_to_display_skeleton():
    from apps.oi.models import ACTION_MODIFY

    with mock.patch(RECENT) as recent_mock, mock.patch(ACTION) as action_mock:
        action_mock.return_value = ACTION_MODIFY
        rev = IssueRevision(changeset=Changeset(),
                            issue=Issue(is_indexed=INDEXED['skeleton']))

        rev._post_commit_to_display()

        assert not recent_mock.called


def test_same_series_revisions():
    with mock.patch('%s.issuerevisions' % CSET) as irevs_mock:
        series = Series()
        ss_revs = mock.MagicMock()
        irevs_mock.filter.return_value = ss_revs
        rev = IssueRevision(changeset=Changeset(), series=series)

        assert rev._same_series_revisions() == ss_revs
        irevs_mock.filter.assert_called_once_with(series=series)


def test_same_series_open_with_after():
    with mock.patch('%s._same_series_revisions' % IREV) as ssrevs_mock:
        ssowa_revs = mock.MagicMock()
        ssrevs_mock.return_value.filter.return_value = ssowa_revs
        rev = IssueRevision()

        assert rev._same_series_open_with_after() == ssowa_revs
        ssrevs_mock.return_value.filter.assert_called_once_with(
            after__isnull=False, committed=None)


@pytest.mark.parametrize('deleted', (True, False))
def test_open_prereq_revisions(deleted):
    if deleted:
        # Sort prereqs from last to first- delete from end of series back.
        sort = '-revision_sort_code'
    else:
        # Add or move from first to last, so that each "after" is in place.
        sort = 'revision_sort_code'

    with mock.patch('%s._same_series_revisions' % IREV) as ssrevs_mock:
        op_revs = mock.MagicMock()
        ssrevs_mock.return_value.exclude.return_value \
                                .filter.return_value \
                                .order_by.return_value = op_revs
        rev = IssueRevision()
        rev.id = 1234
        rev.deleted = deleted

        assert rev._open_prereq_revisions() == op_revs
        ssrevs_mock.return_value.exclude.assert_has_calls([
            mock.call(id=1234),
            mock.call().filter(committed=None),
            mock.call().filter().order_by(sort)])


@pytest.mark.parametrize('deleted', (True, False))
def test_committed_prereq_revisions(deleted):
    # We sort commited reversed from open so that we effectively append
    # to committed as we commit each revision as we walk through open.
    if deleted:
        sort = 'revision_sort_code'
    else:
        sort = '-revision_sort_code'

    with mock.patch('%s._same_series_revisions' % IREV) as ssrevs_mock:
        c_revs = mock.MagicMock()
        ssrevs_mock.return_value.exclude.return_value \
                                .filter.return_value \
                                .order_by.return_value = c_revs
        rev = IssueRevision()
        rev.id = 1234
        rev.deleted = deleted

        assert rev._committed_prereq_revisions() == c_revs
        ssrevs_mock.return_value.exclude.assert_has_calls([
            mock.call(id=1234),
            mock.call().filter(committed=True),
            mock.call().filter().order_by(sort)])
