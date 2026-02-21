# forms.py
from django import forms
from .models import UserAdoptionPost,MissingDogPost


class UserAdoptionPostForm(forms.ModelForm):
    main_image = forms.ImageField(required=True)  # single main image

    class Meta:
        model = UserAdoptionPost
        fields = ['dog_name', 'description', 'location']

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
        ]
        widgets = {
            'date_lost': forms.DateInput(attrs={'type': 'date'}),
            'time_lost': forms.TimeInput(attrs={'type': 'time'}),
        }