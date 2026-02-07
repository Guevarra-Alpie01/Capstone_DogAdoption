from django import forms
from .models import Post
class PostForm(forms.ModelForm):

    rescued_date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date'})
    )

    VIOLATION_CHOICES = [
        ('no_collar', 'No Collar'),
        ('no_leash', 'No Leash'),
        ('no_license', 'No License'),
        ('abandoned', 'Abandoned'),
        ('injured', 'Injured'),
    ]

    violations = forms.MultipleChoiceField(
        choices=VIOLATION_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        required=False
    )

    class Meta:
        model = Post
        fields = [
            'caption',
            'location',
            'status',
            'rescued_date',
            'claim_days',
            'violations',
        ]

    def save(self, commit=True):
        instance = super().save(commit=False)

        # 👇 explicitly store as list (JSON-safe)
        instance.violations = self.cleaned_data.get('violations', [])

        if commit:
            instance.save()
        return instance