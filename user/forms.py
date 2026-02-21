# forms.py
from django import forms
from .models import UserAdoptionPost

class UserAdoptionPostForm(forms.ModelForm):
    main_image = forms.ImageField(required=True)  # single main image

    class Meta:
        model = UserAdoptionPost
        fields = ['dog_name', 'description', 'location']