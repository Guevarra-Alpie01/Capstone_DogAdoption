# forms.py
from django import forms

from dogadoption_admin.barangays import BAYAWAN_BARANGAY_CHOICES
from dogadoption_admin.models import Post

from .models import MissingDogPost, UserAdoptionPost


class RescueFinderForm(forms.Form):
    PURPOSE_CHOICES = [
        ("all", "All"),
        ("claim", "Redeem"),
        ("adopt", "Adopt"),
    ]
    FILTER_FIELDS = (
        "breed",
        "age_group",
        "size_group",
        "gender",
        "coat_length",
        "color",
        "location",
    )

    purpose = forms.ChoiceField(required=False, choices=PURPOSE_CHOICES)
    breed = forms.ChoiceField(required=False, choices=[])
    age_group = forms.ChoiceField(required=False, choices=[])
    size_group = forms.ChoiceField(required=False, choices=[])
    gender = forms.ChoiceField(required=False, choices=[])
    coat_length = forms.ChoiceField(required=False, choices=[])
    color = forms.ChoiceField(required=False, choices=[])
    location = forms.ChoiceField(required=False, choices=[])

    def __init__(self, *args, location_choices=None, default_purpose="all", **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["purpose"].initial = default_purpose
        self.fields["breed"].label = "Breed"
        self.fields["age_group"].label = "Age"
        self.fields["size_group"].label = "Size"
        self.fields["gender"].label = "Gender"
        self.fields["coat_length"].label = "Coat"
        self.fields["color"].label = "Color"
        self.fields["location"].label = "Rescue Location"

        self.fields["breed"].choices = [("", "Any breed"), *Post.BREED_CHOICES]
        self.fields["age_group"].choices = [("", "Any age"), *Post.AGE_GROUP_CHOICES]
        self.fields["size_group"].choices = [("", "Any size"), *Post.SIZE_GROUP_CHOICES]
        self.fields["gender"].choices = [("", "Any gender"), *Post.GENDER_CHOICES]
        self.fields["coat_length"].choices = [("", "Any coat"), *Post.COAT_LENGTH_CHOICES]
        self.fields["color"].choices = [("", "Any color"), *Post.COLOR_CHOICES]
        merged_locations = []
        seen_locations = set()
        for value in [name for name, _label in BAYAWAN_BARANGAY_CHOICES] + list(location_choices or []):
            cleaned = " ".join((value or "").split()).strip()
            if not cleaned:
                continue
            key = cleaned.casefold()
            if key in seen_locations:
                continue
            seen_locations.add(key)
            merged_locations.append((cleaned, cleaned))
        self.fields["location"].choices = [("", "Any location"), *merged_locations]


class UserAdoptionPostForm(forms.ModelForm):
    breed = forms.ChoiceField(
        label="Breed",
        required=True,
        choices=[("", "Select breed"), *Post.BREED_CHOICES],
        widget=forms.Select(),
    )

    breed_other = forms.CharField(
        label="Other Breed",
        required=False,
        widget=forms.TextInput(attrs={
            "placeholder": "Enter breed",
        }),
    )

    age_group = forms.ChoiceField(
        label="Age Group",
        required=True,
        choices=[("", "Select age range"), *Post.AGE_GROUP_CHOICES],
        widget=forms.Select(),
    )

    size_group = forms.ChoiceField(
        label="Size",
        required=True,
        choices=[("", "Select size"), *Post.SIZE_GROUP_CHOICES],
        widget=forms.Select(),
    )

    gender = forms.ChoiceField(
        label="Gender",
        required=True,
        choices=[("", "Select gender"), *UserAdoptionPost.GENDER_CHOICES],
        widget=forms.Select(),
    )

    coat_length = forms.ChoiceField(
        label="Coat Length",
        required=True,
        choices=[("", "Select coat length"), *Post.COAT_LENGTH_CHOICES],
        widget=forms.Select(),
    )

    colors = forms.MultipleChoiceField(
        label="Color",
        required=True,
        choices=Post.COLOR_CHOICES,
        widget=forms.CheckboxSelectMultiple(),
    )

    color_other = forms.CharField(
        label="Other Color",
        required=False,
        widget=forms.TextInput(attrs={
            "placeholder": "Enter other color",
        }),
    )

    location = forms.ChoiceField(
        label="Barangay",
        required=True,
        choices=[("", "Select barangay"), *BAYAWAN_BARANGAY_CHOICES],
        widget=forms.Select(),
    )

    main_image = forms.ImageField(
        required=True,
        widget=forms.ClearableFileInput(attrs={
            "class": "form-control",
            "accept": "image/*",
        }),
    )  # single main image

    class Meta:
        model = UserAdoptionPost
        fields = [
            "dog_name",
            "breed",
            "breed_other",
            "age_group",
            "size_group",
            "gender",
            "coat_length",
            "colors",
            "color_other",
            "age",
            "description",
            "location",
        ]
        widgets = {
            "dog_name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "e.g., Brownie",
            }),
            "age": forms.NumberInput(attrs={
                "class": "form-control",
                "placeholder": "e.g., 2",
                "min": 0,
            }),
            "description": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "Describe the dog, temperament, and any special notes.",
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["age"].required = False
        self.fields["description"].required = False
        for field_name, css_class in {
            "dog_name": "form-control",
            "breed": "form-select",
            "breed_other": "form-control",
            "age_group": "form-select",
            "size_group": "form-select",
            "gender": "form-select",
            "coat_length": "form-select",
            "color_other": "form-control",
            "age": "form-control",
            "description": "form-control",
            "location": "form-select",
        }.items():
            existing = self.fields[field_name].widget.attrs.get("class", "")
            self.fields[field_name].widget.attrs["class"] = f"{existing} {css_class}".strip()
        self.fields["colors"].widget.attrs["class"] = "post-checkbox-grid"
        if self.instance.pk and self.instance.colors:
            self.initial["colors"] = list(self.instance.colors)
        current_location = " ".join((getattr(self.instance, "location", "") or "").split()).strip()
        if current_location and current_location not in [name for name, _label in BAYAWAN_BARANGAY_CHOICES]:
            self.fields["location"].choices = [
                *self.fields["location"].choices,
                (current_location, current_location),
            ]

    def clean_location(self):
        value = " ".join((self.cleaned_data.get("location") or "").split()).strip()
        if not value:
            return value
        valid_barangays = {name for name, _label in BAYAWAN_BARANGAY_CHOICES}
        if value in valid_barangays:
            return value
        current_location = " ".join((getattr(self.instance, "location", "") or "").split()).strip()
        if value and value == current_location:
            return value
        raise forms.ValidationError("Please select a valid barangay from the dropdown list.")

    def clean(self):
        cleaned_data = super().clean()
        breed = cleaned_data.get("breed") or ""
        breed_other = " ".join((cleaned_data.get("breed_other") or "").split()).strip()
        colors = list(dict.fromkeys(cleaned_data.get("colors") or []))
        color_other = " ".join((cleaned_data.get("color_other") or "").split()).strip()

        if breed == Post.BREED_OTHER and not breed_other:
            self.add_error("breed_other", "Enter the breed when Other is selected.")
        elif breed != Post.BREED_OTHER:
            cleaned_data["breed_other"] = ""

        if Post.COLOR_OTHER in colors and not color_other:
            self.add_error("color_other", "Enter the color when Other is selected.")
        elif Post.COLOR_OTHER not in colors:
            cleaned_data["color_other"] = ""

        cleaned_data["colors"] = colors
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.colors = self.cleaned_data.get("colors") or []
        if commit:
            instance.save()
            self.save_m2m()
        return instance

class MissingDogPostForm(forms.ModelForm):
    class Meta:
        model = MissingDogPost
        fields = [
            'dog_name',
            'age',
            'description',
            'image',
            'date_lost',
            'time_lost',
            'location',
            'contact_phone_number',
            'contact_facebook_url',
        ]
        widgets = {
            "dog_name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "e.g., Max",
            }),
            "age": forms.NumberInput(attrs={
                "class": "form-control",
                "placeholder": "e.g., 4",
                "min": 0,
            }),
            "description": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "Include markings, collar color, and where last seen.",
            }),
            "image": forms.ClearableFileInput(attrs={
                "class": "form-control",
                "accept": "image/*",
            }),
            "date_lost": forms.DateInput(attrs={
                "class": "form-control",
                "type": "date",
            }),
            "time_lost": forms.TimeInput(attrs={
                "class": "form-control",
                "type": "time",
            }),
            "location": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Exact location where the dog was last seen",
            }),
            "contact_phone_number": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Optional phone number for contact",
            }),
            "contact_facebook_url": forms.URLInput(attrs={
                "class": "form-control",
                "placeholder": "Optional Facebook profile link",
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["age"].required = False
        self.fields["description"].required = False
