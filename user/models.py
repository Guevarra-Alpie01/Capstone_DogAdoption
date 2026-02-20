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
    profile_image = models.ImageField(
    upload_to ="profile_images/",
    default="profile_images/default-user-image.jpg")
    created_at = models.DateTimeField(auto_now_add=True)
    
#request dog capture
class DogCaptureRequest(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('declined', 'Declined'),
    )

    requested_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='dog_requests')
    assigned_admin = models.ForeignKey(
        User, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='assigned_captures'
    )

    reason = models.CharField(max_length=50)
    description = models.TextField(blank=True, null=True)

    # GPS location
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    # Manual location
    barangay = models.CharField(max_length=100, null=True, blank=True)
    city = models.CharField(max_length=100, null=True, blank=True)

    image = models.ImageField(upload_to='dog_requests/', null=True, blank=True)

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    scheduled_date = models.DateTimeField(null=True, blank=True)
    admin_message = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.requested_by} - {self.reason} ({self.status})"


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
