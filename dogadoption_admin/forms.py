from django import forms
from .models import Post
class PostForm(forms.ModelForm):

    caption = forms.CharField(
        label="Dog Name",
        required=False,
        widget=forms.TextInput(attrs={
            'placeholder': 'Enter dog name'
        })
    )

    rescued_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date'})
    )

    location = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'placeholder': 'Enter Barangay',
            'autocomplete': 'off',
        })
    )

    claim_days = forms.IntegerField(
        required=True,
        min_value=1,
        widget=forms.NumberInput(attrs={
            'type': 'number',
            'inputmode': 'numeric',
            'min': '1',
            'step': '1',
        })
    )

    class Meta:
        model = Post
        fields = [
            'caption',
            'location',
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
