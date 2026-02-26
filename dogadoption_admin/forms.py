from django import forms
from .models import Post
class PostForm(forms.ModelForm):

    rescued_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date'})
    )

    class Meta:
        model = Post
        fields = [
            'caption',
            'location',
            'status',
            'rescued_date',
            'claim_days',
        ]
    

from .models import Citation, Penalty,PenaltySection
from user.models import User

class CitationForm(forms.ModelForm):
    owner = forms.ModelChoiceField(
        queryset=User.objects.all(),
        label="Search Owner",
        widget=forms.Select(attrs={
            "class": "user-search",
        })
    )

    class Meta:
        model = Citation
        fields = ['owner']

class SectionForm(forms.ModelForm):
    class Meta:
        model = PenaltySection
        fields = ['number']
        labels = {
            'number': 'Section Number'
        }


class PenaltyForm(forms.ModelForm):
    class Meta:
        model = Penalty
        fields = ['section', 'number', 'title', 'amount', 'active']
