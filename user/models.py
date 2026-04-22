from django.db import models
from django.contrib.auth.models import User
from django.conf import settings
from dogadoption_admin.models import Post, PostRequest


#users profile for sign up
class FaceImage(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    image = models.ImageField(upload_to="face_auth/")
    created_at = models.DateTimeField(auto_now_add=True)

class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    middle_initial = models.CharField(max_length=1, blank=True)
    address = models.TextField()
    age = models.IntegerField()
    consent_given = models.BooleanField(default=False)
    email_verified = models.BooleanField(default=True)
    notification_read_keys = models.JSONField(default=list, blank=True)
    phone_number = models.CharField(max_length=20, blank=True)
    facebook_url = models.URLField(blank=True)
    profile_image = models.ImageField(
    upload_to ="profile_images/",
    default="profile_images/default-user-image.jpg")
    created_at = models.DateTimeField(auto_now_add=True)
    
#request dog capture
class DogCaptureRequest(models.Model):
    REQUEST_TYPE_CHOICES = (
        ("capture", "Request Dog Capture"),
        ("surrender", "Request Dog Surrender"),
    )

    SUBMISSION_TYPE_CHOICES = (
        ("walk_in", "Walk-in Request (Office)"),
        ("online", "Online Request"),
    )

    REASON_LABELS = {
        'biting': 'Dog is biting people',
        'aggressive': 'Dog is aggressive',
        'injured': 'Dog is injured',
        'sick': 'Dog looks sick',
        'stray': 'Stray dog',
        'other': 'Other',
    }

    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('captured', 'Captured'),
        ('declined', 'Declined'),
    )

    requested_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='dog_requests')
    assigned_admin = models.ForeignKey(
        User, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='assigned_captures'
    )

    request_type = models.CharField(
        max_length=20,
        choices=REQUEST_TYPE_CHOICES,
        default="surrender",
    )
    submission_type = models.CharField(
        max_length=20,
        choices=SUBMISSION_TYPE_CHOICES,
        default="online",
        null=True,
        blank=True,
    )
    preferred_appointment_date = models.DateField(null=True, blank=True)

    reason = models.CharField(max_length=50)
    description = models.TextField(blank=True, null=True)

    # GPS location
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    # Manual location
    barangay = models.CharField(max_length=100, null=True, blank=True)
    city = models.CharField(max_length=100, null=True, blank=True)
    manual_full_address = models.TextField(null=True, blank=True)
    location_landmark_image = models.ImageField(
        upload_to='dog_request_landmarks/',
        null=True,
        blank=True
    )

    image = models.ImageField(upload_to='dog_requests/', null=True, blank=True)

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    scheduled_date = models.DateTimeField(null=True, blank=True)
    captured_at = models.DateTimeField(null=True, blank=True)
    admin_message = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "created_at"], name="dogcap_status_created_idx"),
            models.Index(fields=["requested_by", "status", "created_at"], name="dogcap_user_status_created_idx"),
            models.Index(fields=["assigned_admin", "status"], name="dogcap_admin_status_idx"),
            models.Index(
                fields=["status", "scheduled_date", "created_at"],
                name="dogcap_stat_sched_cr_idx",
            ),
            models.Index(
                fields=["status", "latitude", "longitude", "created_at"],
                name="dogcap_stat_coords_cr_idx",
            ),
        ]

    def get_reason_display(self):
        return self.REASON_LABELS.get(self.reason, self.reason.replace('_', ' ').title() if self.reason else 'Unknown')

    @property
    def needs_location_details(self):
        return self.submission_type == "online"

    @property
    def uses_appointment_date(self):
        return self.submission_type == "walk_in"

    def __str__(self):
        return f"{self.requested_by} - {self.get_request_type_display()} ({self.status})"


class DogCaptureRequestImage(models.Model):
    request = models.ForeignKey(
        DogCaptureRequest,
        on_delete=models.CASCADE,
        related_name='images'
    )
    image = models.ImageField(upload_to='dog_requests/')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Capture request {self.request_id} image"


class DogCaptureRequestLandmarkImage(models.Model):
    request = models.ForeignKey(
        DogCaptureRequest,
        on_delete=models.CASCADE,
        related_name='landmark_images'
    )
    image = models.ImageField(upload_to='dog_request_landmarks/')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Capture request {self.request_id} landmark image"


class AdoptionRequest(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('declined', 'Declined'),
    )

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='adoption_requests')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    requested_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'post')  # user can request once

    def __str__(self):
        return f"{self.user} - {self.post} ({self.status})"
    

class OwnerClaim(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    )

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='claims')

    explanation = models.TextField(blank=True)
    last_known_location = models.CharField(max_length=255, blank=True)

    face_verified = models.BooleanField(default=False)

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    submitted_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user} - {self.post} ({self.status})"

class ClaimImage(models.Model):
    claim = models.ForeignKey(
        PostRequest,
        related_name='images',
        on_delete=models.CASCADE
    )
    image = models.ImageField(upload_to='claim_images/')


#user post for adoption 
class UserAdoptionPost(models.Model):
    BREED_OTHER = Post.BREED_OTHER
    COLOR_OTHER = Post.COLOR_OTHER
    BREED_CHOICES = Post.BREED_CHOICES
    AGE_GROUP_CHOICES = Post.AGE_GROUP_CHOICES
    SIZE_GROUP_CHOICES = Post.SIZE_GROUP_CHOICES
    GENDER_CHOICES = [
        ("male", "Male"),
        ("female", "Female"),
    ]
    COAT_LENGTH_CHOICES = Post.COAT_LENGTH_CHOICES
    COLOR_CHOICES = Post.COLOR_CHOICES

    STATUS_CHOICES = [
        ('pending_review', 'Pending Review'),
        ('available', 'Available'),
        ('adopted', 'Adopted'),
        ('declined', 'Declined'),
    ]

    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='adoption_posts'
    )

    dog_name = models.CharField(max_length=100)
    breed = models.CharField(max_length=40, choices=BREED_CHOICES, blank=True, default="")
    breed_other = models.CharField(max_length=100, blank=True, default="")
    age_group = models.CharField(max_length=20, choices=AGE_GROUP_CHOICES, blank=True, default="")
    size_group = models.CharField(max_length=20, choices=SIZE_GROUP_CHOICES, blank=True, default="")
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES, blank=True, default="")
    coat_length = models.CharField(max_length=20, choices=COAT_LENGTH_CHOICES, blank=True, default="")
    colors = models.JSONField(blank=True, default=list)
    color_other = models.CharField(max_length=100, blank=True, default="")
    age = models.PositiveIntegerField(null=True, blank=True)
    description = models.TextField(blank=True)
    location = models.CharField(max_length=255)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending_review'
    )

    is_vaccinated = models.BooleanField(default=False)
    is_registered = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "created_at"], name="uadoptpost_status_created_idx"),
            models.Index(fields=["owner", "status"], name="uadoptpost_owner_status_idx"),
        ]

    @staticmethod
    def _clean_text(value):
        return " ".join((value or "").split()).strip()

    @property
    def display_breed(self):
        if self.breed == self.BREED_OTHER:
            return self._clean_text(self.breed_other) or "Other"
        if self.breed:
            return self.get_breed_display()
        return ""

    @property
    def display_age_group(self):
        return self.get_age_group_display() if self.age_group else ""

    @property
    def display_size_group(self):
        return self.get_size_group_display() if self.size_group else ""

    @property
    def display_coat_length(self):
        return self.get_coat_length_display() if self.coat_length else ""

    @property
    def display_color_list(self):
        raw_colors = self.colors or []
        if isinstance(raw_colors, str):
            raw_colors = [raw_colors]
        color_labels = []
        choice_map = dict(self.COLOR_CHOICES)
        for value in raw_colors:
            if value == self.COLOR_OTHER:
                other_label = self._clean_text(self.color_other)
                if other_label:
                    color_labels.append(other_label)
                elif "Other" not in color_labels:
                    color_labels.append("Other")
                continue
            label = choice_map.get(value)
            if label and label not in color_labels:
                color_labels.append(label)
        return color_labels

    @property
    def display_colors(self):
        return ", ".join(self.display_color_list)

    @property
    def main_image(self):
        return self.images.first()

    def __str__(self):
        return f"{self.dog_name} - {self.owner.username}"


class UserAdoptionImage(models.Model):
    post = models.ForeignKey(
        UserAdoptionPost,
        related_name='images',
        on_delete=models.CASCADE
    )
    image = models.ImageField(upload_to='user_adoption/')


class UserAdoptionRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    post = models.ForeignKey(
        UserAdoptionPost,
        related_name='requests',
        on_delete=models.CASCADE
    )

    requester = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='adoption_requests'
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending'
    )

    valid_id = models.ImageField(upload_to='adoption_docs/ids/', null=True, blank=True)
    vaccination_history = models.ImageField(upload_to='adoption_docs/vaccines/', null=True, blank=True)
    anti_rabies_proof = models.ImageField(upload_to='adoption_docs/anti_rabies/', null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('post', 'requester')
        indexes = [
            models.Index(fields=["post", "status"], name="uadoptreq_post_status_idx"),
            models.Index(fields=["requester", "status"], name="uadoptreq_req_status_idx"),
        ]

    def __str__(self):
        return f"{self.requester.username} → {self.post.dog_name}"
    

#post for lost dogs

class MissingDogPost(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE)
    
    dog_name = models.CharField(max_length=100)
    age = models.PositiveIntegerField(null=True, blank=True)
    description = models.TextField(blank=True)

    image = models.ImageField(upload_to='missing_dogs/')
    
    date_lost = models.DateField()
    time_lost = models.TimeField()

    location = models.CharField(max_length=255)
    contact_phone_number = models.CharField(max_length=20, blank=True)
    contact_facebook_url = models.URLField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    STATUS_CHOICES = [
        ('pending_review', 'Pending Review'),
        ('missing', 'Missing'),
        ('found', 'Found'),
        ('declined', 'Declined'),
    ]

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending_review'
    )

    class Meta:
        indexes = [
            models.Index(fields=["status", "created_at"], name="missingdog_status_created_idx"),
            models.Index(fields=["owner", "status"], name="missingdog_owner_status_idx"),
        ]

    def __str__(self):
        return f"{self.dog_name} - {self.status}"
