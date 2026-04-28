from django import forms
from django.contrib.auth.hashers import make_password
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.validators import ASCIIUsernameValidator
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.urls import reverse_lazy

from .access import STAFF_PERMISSION_FIELDS, clear_admin_access_cache
from .barangays import BAYAWAN_BARANGAYS, BAYAWAN_BARANGAY_CHOICES
from .models import Barangay, Citation, DeceasedDog, Penalty, PenaltySection, Post, VetAdminProfile


class PostForm(forms.ModelForm):

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
            'placeholder': 'Enter breed',
        })
    )

    age_group = forms.ChoiceField(
        label="Age",
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

    rescued_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date'})
    )

    gender = forms.ChoiceField(
        required=True,
        choices=[("", "Select gender"), *Post.GENDER_CHOICES],
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
            'placeholder': 'Enter other color',
        })
    )

    location = forms.ChoiceField(
        required=False,
        choices=[("", "Select barangay"), *BAYAWAN_BARANGAY_CHOICES],
        widget=forms.Select(),
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
            'breed',
            'breed_other',
            'age_group',
            'size_group',
            'gender',
            'coat_length',
            'colors',
            'color_other',
            'location',
            'rescued_date',
            'claim_days',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, css_class in {
            "breed": "form-select",
            "breed_other": "form-control",
            "age_group": "form-select",
            "size_group": "form-select",
            "gender": "form-select",
            "coat_length": "form-select",
            "color_other": "form-control",
            "location": "form-select",
            "rescued_date": "form-control",
            "claim_days": "form-control",
        }.items():
            existing = self.fields[field_name].widget.attrs.get("class", "")
            merged = f"{existing} {css_class}".strip()
            self.fields[field_name].widget.attrs["class"] = merged
        self.fields["colors"].widget.attrs["class"] = "post-checkbox-grid"
        if self.instance.pk and self.instance.colors:
            self.initial["colors"] = list(self.instance.colors)
        current_location = " ".join((getattr(self.instance, "location", "") or "").split()).strip()
        if current_location and current_location not in BAYAWAN_BARANGAYS:
            self.fields["location"].choices = [
                *self.fields["location"].choices,
                (current_location, current_location),
            ]

    def clean_location(self):
        value = " ".join((self.cleaned_data.get("location") or "").split()).strip()
        if not value:
            return value
        if value in BAYAWAN_BARANGAYS:
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

        breed = self.cleaned_data.get("breed") or ""
        breed_other = self.cleaned_data.get("breed_other") or ""
        if breed == Post.BREED_OTHER:
            instance.caption = breed_other or "Other"
        else:
            instance.caption = dict(Post.BREED_CHOICES).get(breed, instance.caption or "")

        if commit:
            instance.save()
            self.save_m2m()
        return instance
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


class ManagedStaffAccountForm(forms.Form):
    username_validator = ASCIIUsernameValidator()

    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "staff_username"}),
    )
    password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(
            attrs={"class": "form-control", "placeholder": "Use at least 8 characters"}
        ),
    )
    confirm_password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(
            attrs={"class": "form-control", "placeholder": "Repeat the password"}
        ),
    )
    is_active = forms.BooleanField(required=False, initial=True)
    can_create_posts = forms.BooleanField(required=False)
    can_view_post_history = forms.BooleanField(required=False)
    can_view_status_cards = forms.BooleanField(required=False)
    can_manage_capture_requests = forms.BooleanField(required=False)
    can_access_registration = forms.BooleanField(required=False)
    can_access_registration_list = forms.BooleanField(required=False)
    can_access_vaccination = forms.BooleanField(required=False)
    can_access_vaccination_list = forms.BooleanField(required=False)
    can_access_citations = forms.BooleanField(required=False)

    def __init__(self, *args, instance=None, require_password=True, **kwargs):
        self.instance = instance
        self.require_password = require_password
        super().__init__(*args, **kwargs)

        if instance is not None:
            self.fields["username"].initial = instance.username
            self.fields["is_active"].initial = instance.is_active
            try:
                access = instance.staff_access
            except VetAdminProfile.DoesNotExist:
                access = None
            if access is not None:
                for field_name in STAFF_PERMISSION_FIELDS:
                    self.fields[field_name].initial = bool(getattr(access, field_name, False))

        password_help = "Required for new staff accounts." if require_password else "Leave blank to keep the current password."
        self.fields["password"].help_text = password_help

        for name in (*STAFF_PERMISSION_FIELDS, "is_active"):
            self.fields[name].widget.attrs["class"] = "form-check-input"

    def clean_username(self):
        username = " ".join((self.cleaned_data.get("username") or "").split()).strip()
        if not username:
            raise forms.ValidationError("Username is required.")
        self.username_validator(username)
        query = User.objects.filter(username__iexact=username)
        if self.instance is not None:
            query = query.exclude(pk=self.instance.pk)
        if query.exists():
            raise forms.ValidationError("That username is already in use.")
        return username

    def _at_least_one_permission_selected(self, cleaned_data):
        """True if any access checkbox is on (use POST data so we match browser checkbox behavior)."""
        for name in STAFF_PERMISSION_FIELDS:
            if cleaned_data.get(name):
                return True
        if self.data is not None:
            for name in STAFF_PERMISSION_FIELDS:
                key = self.add_prefix(name)
                if self.data.get(key) not in (None, ""):
                    return True
        return False

    def clean(self):
        cleaned_data = super().clean()
        is_create = self.instance is None or not getattr(self.instance, "pk", None)
        # Unchecked checkboxes are omitted from POST; default new staff to active
        # so they can authenticate (ModelBackend refuses inactive users).
        active_key = self.add_prefix("is_active")
        if is_create and self.is_bound and self.data is not None and active_key not in self.data:
            cleaned_data["is_active"] = True
        password = cleaned_data.get("password") or ""
        confirm_password = cleaned_data.get("confirm_password") or ""
        username = cleaned_data.get("username") or ""

        if self.require_password and not password:
            self.add_error("password", "Password is required for new staff accounts.")

        if password or confirm_password:
            if password != confirm_password:
                self.add_error("confirm_password", "Password confirmation does not match.")
            else:
                temp_user = self.instance or User(username=username)
                try:
                    validate_password(password, user=temp_user)
                except ValidationError as exc:
                    self.add_error("password", exc)

        if not self._at_least_one_permission_selected(cleaned_data):
            self.add_error(
                None,
                "Select at least one access permission for this staff account.",
            )

        return cleaned_data

    def save(self):
        if self.instance is None:
            user = User(is_staff=True)
        else:
            user = self.instance

        user.username = self.cleaned_data["username"]
        user.is_staff = True
        user.is_active = bool(self.cleaned_data.get("is_active"))
        raw_password = (self.cleaned_data.get("password") or "").strip()

        # One hash for auth_user and VetAdminProfile (do not call make_password twice: salts differ).
        if raw_password:
            password_hash = make_password(raw_password)
            user.password = password_hash
        # Update without new password: keep existing user hash for profile row too.
        user.save()
        if raw_password:
            profile_password = password_hash
        else:
            profile_password = user.password

        profile_defaults = {
            name: bool(self.cleaned_data.get(name)) for name in STAFF_PERMISSION_FIELDS
        }
        profile_defaults["username"] = user.username
        profile_defaults["password"] = profile_password
        VetAdminProfile.objects.update_or_create(user=user, defaults=profile_defaults)
        clear_admin_access_cache(user)
        return user


class DeceasedDogLogForm(forms.ModelForm):
    """Log a deceased dog tied to an existing shelter post (snapshot filled on save)."""

    class Meta:
        model = DeceasedDog
        fields = ("post", "deceased_at", "notes")
        widgets = {
            "post": forms.Select(attrs={"class": "form-control"}),
            "deceased_at": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "notes": forms.Textarea(
                attrs={"rows": 3, "class": "form-control", "placeholder": "Optional notes"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["post"].queryset = Post.objects.order_by("-created_at", "-id").only(
            "id",
            "caption",
            "breed",
            "breed_other",
            "age_group",
            "size_group",
            "gender",
            "coat_length",
            "colors",
            "color_other",
            "location",
            "status",
            "rescued_date",
            "created_at",
        )
        self.fields["post"].label = "Origin post"
        self.fields["deceased_at"].label = "Date deceased"
        self.fields["notes"].label = "Notes"
        self.fields["notes"].required = False
        self.fields["post"].label_from_instance = (
            lambda p: f"#{p.pk} — {p.display_title or p.caption or 'Dog post'}"
        )

