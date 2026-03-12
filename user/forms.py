# forms.py
from django import forms
from .models import UserAdoptionPost,MissingDogPost


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
        fields = ['dog_name', 'gender', 'description', 'location']
        widgets = {
            "dog_name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "e.g., Brownie",
            }),
            "gender": forms.Select(attrs={
                "class": "form-select",
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
        self.fields["gender"].choices = [
            ("", "Select gender"),
            *UserAdoptionPost.GENDER_CHOICES,
        ]

class MissingDogPostForm(forms.ModelForm):
    class Meta:
        model = MissingDogPost
        fields = [
            'dog_name',
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
