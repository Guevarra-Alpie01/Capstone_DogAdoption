from django import forms
from django.urls import reverse_lazy

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

    gender = forms.ChoiceField(
        required=False,
        choices=[("", "Gender (Optional)"), *Post.GENDER_CHOICES],
        widget=forms.Select(),
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
            'gender',
            'location',
            'rescued_date',
            'claim_days',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, css_class in {
            "caption": "form-control",
            "gender": "form-select",
            "location": "form-control",
            "rescued_date": "form-control",
            "claim_days": "form-control",
        }.items():
            existing = self.fields[field_name].widget.attrs.get("class", "")
            merged = f"{existing} {css_class}".strip()
            self.fields[field_name].widget.attrs["class"] = merged

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

    owner_first_name = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={'placeholder': 'First name'}),
    )
    owner_last_name = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={'placeholder': 'Last name'}),
    )
    owner_barangay = forms.CharField(
        max_length=255,
        required=True,
        widget=forms.TextInput(attrs={
            'placeholder': 'Barangay',
            'autocomplete': 'off',
            'data-barangay-autocomplete': 'true',
            'data-barangay-suggestions-id': 'citation-barangay-suggestions',
            'data-barangay-strict': 'true',
        }),
    )

    class Meta:
        model = Citation
        fields = ['owner', 'owner_first_name', 'owner_last_name', 'owner_barangay']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['owner_barangay'].widget.attrs['data-barangay-source-url'] = reverse_lazy(
            'dogadoption_admin:barangay_list_api'
        )

    def clean_owner_barangay(self):
        value = " ".join((self.cleaned_data.get("owner_barangay") or "").split()).strip()
        if not value:
            return value

        normalized = "".join(ch.lower() for ch in value if ch.isalnum())
        for name in Barangay.objects.filter(is_active=True).values_list("name", flat=True):
            if "".join(ch.lower() for ch in name if ch.isalnum()) == normalized:
                return name

        raise forms.ValidationError("Please select a valid barangay from the suggestions.")

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
