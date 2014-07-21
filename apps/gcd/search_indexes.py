from haystack import indexes
from apps.gcd.models import Issue, Series, Story, Publisher, IndiciaPublisher,\
    Brand, BrandGroup, STORY_TYPES

DEFAULT_BOOST = 15.0

class ObjectIndex(object):
    def index_queryset(self, using=None):
        """Used when the entire index for model is updated."""
        return self.get_model().objects.filter(deleted=False)

    def get_updated_field(self):
        return "modified"

    def prepare_year(self, obj):
        if obj.year_began:
            return obj.year_began
        else:
            return 9999

    def prepare(self, obj):
        self.prepared_data = super(ObjectIndex, self).prepare(obj)

        self.prepared_data['sort_name'] = \
          self.prepared_data['sort_name'].lower()

        return self.prepared_data

class IssueIndex(ObjectIndex, indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(document=True, use_template=True)
    title = indexes.CharField(model_attr="title", boost=DEFAULT_BOOST)
    facet_model_name = indexes.CharField(faceted=True)

    sort_name = indexes.CharField(model_attr='series__sort_name',
                                  indexed=False)
    key_date = indexes.CharField(model_attr='key_date', indexed=False)
    sort_code = indexes.IntegerField(model_attr='sort_code', indexed=False)
    year = indexes.IntegerField()
    country = indexes.CharField(model_attr='series__country__code',
                                indexed=False)

    def get_model(self):
        return Issue

    def prepare_facet_model_name(self, obj):
        return "issue"

    def prepare_year(self, obj):
        if obj.key_date:
            return int(obj.key_date[:4])
        else:
            return 9999

    def prepare_key_date(self, obj):
        if obj.key_date:
            return obj.key_date
        else:
            return "9999-99-99"


class SeriesIndex(ObjectIndex, indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(document=True, use_template=True)
    name = indexes.CharField(model_attr="name", boost=DEFAULT_BOOST)
    facet_model_name = indexes.CharField(faceted=True)

    sort_name = indexes.CharField(model_attr='sort_name', indexed=False)
    year = indexes.IntegerField()
    country = indexes.CharField(model_attr='country__code', indexed=False)
    title_search = indexes.CharField()

    def get_model(self):
        return Series

    def prepare_facet_model_name(self, obj):
        return "series"

    def prepare_title_search(self, obj):
        name = obj.name
        if obj.has_issue_title:
            for issue in obj.active_issues():
                if issue.title:
                    name += '\n' + issue.title
        return name


class StoryIndex(ObjectIndex, indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(document=True, use_template=True)
    title = indexes.CharField(model_attr="title", boost=DEFAULT_BOOST)
    facet_model_name = indexes.CharField(faceted=True)

    sort_name = indexes.CharField(model_attr='issue__series__sort_name',
                                  indexed=False)
    key_date = indexes.CharField(model_attr='issue__key_date', indexed=False)
    sort_code = indexes.IntegerField(model_attr='issue__sort_code',
                                     indexed=False)
    sequence_number = indexes.IntegerField(model_attr='sequence_number',
                                           indexed=False)
    type = indexes.CharField(model_attr='type__name', indexed=False)
    year = indexes.IntegerField()
    country = indexes.CharField(model_attr='issue__series__country__code',
                                indexed=False)

    def get_model(self):
        return Story

    def prepare_facet_model_name(self, obj):
        return "story"

    def prepare_year(self, obj):
        if obj.issue.key_date:
            return int(obj.issue.key_date[:4])
        else:
            return 9999

    def prepare_key_date(self, obj):
        if obj.issue.key_date:
            return obj.issue.key_date
        else:
            return "9999-99-99"

    def index_queryset(self, using=None):
        """Used when the entire index for model is updated."""
        return super(ObjectIndex, self).index_queryset(using).exclude(
            type=STORY_TYPES['blank'])


class PublisherIndex(ObjectIndex, indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(document=True,
                             use_template=True,
                             template_name=
                             'search/indexes/gcd/publisher_text.txt')
    name = indexes.CharField(model_attr="name", boost=DEFAULT_BOOST)
    facet_model_name = indexes.CharField(faceted=True)

    sort_name = indexes.CharField(model_attr='name', indexed=False)
    year = indexes.IntegerField()
    country = indexes.CharField(model_attr='country__code', indexed=False)

    def get_model(self):
        return Publisher

    def prepare_facet_model_name(self, obj):
        return "publisher"


class IndiciaPublisherIndex(ObjectIndex, indexes.SearchIndex,
                            indexes.Indexable):
    text = indexes.CharField(document=True,
                             use_template=True,
                             template_name=
                             'search/indexes/gcd/publisher_text.txt')
    name = indexes.CharField(model_attr="name", boost=DEFAULT_BOOST)
    facet_model_name = indexes.CharField(faceted=True)

    sort_name = indexes.CharField(model_attr='name', indexed=False)
    year = indexes.IntegerField()
    country = indexes.CharField(model_attr='country__code', indexed=False)

    def get_model(self):
        return IndiciaPublisher

    def prepare_facet_model_name(self, obj):
        return "indicia publisher"


class BrandIndex(ObjectIndex, indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(document=True,
                             use_template=True,
                             template_name=
                             'search/indexes/gcd/publisher_text.txt')
    name = indexes.CharField(model_attr="name", boost=DEFAULT_BOOST)
    facet_model_name = indexes.CharField(faceted=True)

    sort_name = indexes.CharField(model_attr='name', indexed=False)
    year = indexes.IntegerField()

    def get_model(self):
        return Brand

    def prepare_facet_model_name(self, obj):
        return "brand emblem"


class BrandGroupIndex(ObjectIndex, indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(document=True,
                             use_template=True,
                             template_name=
                             'search/indexes/gcd/publisher_text.txt')
    name = indexes.CharField(model_attr="name", boost=DEFAULT_BOOST)
    facet_model_name = indexes.CharField(faceted=True)

    sort_name = indexes.CharField(model_attr='name', indexed=False)
    year = indexes.IntegerField()
    country = indexes.CharField(model_attr='parent__country__code',
                                indexed=False)

    def get_model(self):
        return BrandGroup

    def prepare_facet_model_name(self, obj):
        return "brand group"
