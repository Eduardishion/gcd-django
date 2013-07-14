from django import forms
from apps.gcd.models import Publisher, Country, Language

PUBLISHERS = [[p.id, p.name]
                  for p in Publisher.objects
                                    .filter(is_master=True,
                                            deleted=False)
                                    .order_by('name')]
class IssuesWithCoversForm(forms.Form):
    """
    Form for filtering the listing of issues with several covers.
    """
    publisher = forms.ChoiceField(required=False,
                                  choices=PUBLISHERS,
                                  initial=54)

class ReprintInspectionForm(forms.Form):
    """
    Form for filtering the listing of issues with identical issue and cover notes.
    """
    choices = [['', '--']]
    choices.extend(PUBLISHERS)
    languages = [['', '--']]
    languages.extend([l.id, l.name] for l in Language.objects.order_by('name'))
    publisher = forms.ChoiceField(required=False,
                                  choices=choices)
    country = forms.ChoiceField(required=False,
                                choices=IMPRINTS_IN_USE_COUNTRIES,
                                initial='')
    language = forms.ChoiceField(required=False,
                                choices=languages,
                                initial='')
                                
