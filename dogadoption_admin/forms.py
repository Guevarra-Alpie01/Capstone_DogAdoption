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
        labels = {
            'caption': 'Dog Description',
            'location': 'Location (Optional)',
            'status': 'Current Status',
            'rescued_date': 'Rescued Date',
            'claim_days': 'Claim/Adoption Window (Days)',
            'violations': 'Reported Violations',
        }
        help_texts = {
            'claim_days': 'Number of days that owners can claim the dog before adoption-only processing.',
        }
        widgets = {
            'caption': forms.Textarea(attrs={'rows': 4}),
            'location': forms.TextInput(),
            'status': forms.Select(),
            'claim_days': forms.NumberInput(attrs={'min': 1, 'max': 30}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for name, field in self.fields.items():
            if name == 'violations':
                field.widget.attrs.update({'class': 'violations-list'})
                continue

            widget = field.widget
            if isinstance(widget, forms.Textarea):
                control_class = 'ui-textarea'
            elif isinstance(widget, forms.Select):
                control_class = 'ui-select'
            else:
                control_class = 'ui-input'

            existing = widget.attrs.get('class', '')
            widget.attrs['class'] = f"{existing} {control_class}".strip()

        self.fields['caption'].widget.attrs.setdefault(
            'placeholder',
            'Describe the dog, behavior, and context of rescue.'
        )
        self.fields['location'].widget.attrs.setdefault(
            'placeholder',
            'Street, barangay, or landmark'
        )
        self.fields['rescued_date'].widget.attrs.setdefault('class', 'ui-input')

    def save(self, commit=True):
        instance = super().save(commit=False)

        # 👇 explicitly store as list (JSON-safe)
        instance.violations = self.cleaned_data.get('violations', [])

        if commit:
            instance.save()
        return instance
