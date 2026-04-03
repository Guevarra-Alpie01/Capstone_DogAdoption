# forms.py
from django import forms

from dogadoption_admin.models import Post

from .models import MissingDogPost, UserAdoptionPost


class RescueFinderForm(forms.Form):
    PURPOSE_CHOICES = [
        ("all", "All"),
        ("claim", "Claim"),
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
        self.fields["location"].choices = [
            ("", "Any location"),
            *((value, value) for value in (location_choices or [])),
        ]


class UserAdoptionPostForm(forms.ModelForm):
    main_image = forms.ImageField(
        required=True,
        widget=forms.ClearableFileInput(attrs={
            "class": "form-control",
            "accept": "image/*",
        }),
    )  # single main image

    class Meta:
        model = UserAdoptionPost
        fields = ['dog_name', 'gender', 'age', 'description', 'location']
        widgets = {
            "dog_name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "e.g., Brownie",
            }),
            "gender": forms.Select(attrs={
                "class": "form-select",
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
            "location": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Barangay, street, or landmark",
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["gender"].required = True
        self.fields["age"].required = False
        self.fields["description"].required = False
        self.fields["gender"].choices = [
            ("", "Select gender"),
            *UserAdoptionPost.GENDER_CHOICES,
        ]

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
