from django import forms
from .models import Post, Barangay
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
            'data-barangay-autocomplete': 'true',
            'data-barangay-suggestions-id': 'location-suggestions',
            'data-barangay-strict': 'true',
        })
    )

    claim_days = forms.IntegerField(
        required=True,
        min_value=0,
        widget=forms.NumberInput(attrs={
            'type': 'number',
            'inputmode': 'numeric',
            'min': '0',
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

    def clean_location(self):
        value = " ".join((self.cleaned_data.get("location") or "").split()).strip()
        if not value:
            return value

        normalized = "".join(ch.lower() for ch in value if ch.isalnum())
        for name in Barangay.objects.filter(is_active=True).values_list("name", flat=True):
            if "".join(ch.lower() for ch in name if ch.isalnum()) == normalized:
                return name

        raise forms.ValidationError("Please select a valid barangay from the suggestions.")
    

from .models import Citation, Penalty,PenaltySection
from user.models import User

class CitationForm(forms.ModelForm):
    owner = forms.ModelChoiceField(
        queryset=User.objects.filter(is_staff=False).order_by('username'),
        label="Search Owner",
        required=False,
        widget=forms.HiddenInput(),
    )

    owner_first_name = forms.CharField(max_length=150, required=True)
    owner_last_name = forms.CharField(max_length=150, required=True)
    owner_barangay = forms.CharField(max_length=255, required=True)

    class Meta:
        model = Citation
        fields = ['owner', 'owner_first_name', 'owner_last_name', 'owner_barangay']
        widgets = {
            'owner_first_name': forms.TextInput(attrs={'placeholder': 'First name'}),
            'owner_last_name': forms.TextInput(attrs={'placeholder': 'Last name'}),
            'owner_barangay': forms.TextInput(attrs={'placeholder': 'Barangay'}),
        }

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
        fields = ['section', 'number', 'title', 'amount']
