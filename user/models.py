from django.db import models
from django.contrib.auth.models import User


#users profile for sign up
class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)

    middle_initial = models.CharField(max_length=1, blank=True)
    address = models.TextField()
    age = models.PositiveIntegerField()

    def __str__(self):
        return self.user.username
    
#request dog capture
class DogCaptureRequest(models.Model):
    CAPTURE_CHOICES = [
        ('biting', 'Dog is biting people'),
        ('aggressive', 'Dog is aggressive'),
        ('injured', 'Dog is injured'),
        ('sick', 'Dog looks sick'),
        ('stray', 'Stray dog'),
        ('other', 'Other'),
    ]

    requested_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='dog_requests'
    )

    assigned_admin = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_requests',
        limit_choices_to={'is_staff': True}
    )

    reason = models.CharField(max_length=50, choices=CAPTURE_CHOICES)
    description = models.TextField(blank=True)

    image = models.ImageField(
        upload_to='dog_requests/',
        null=True,
        blank=True
    )

    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True
    )

    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.reason} - {self.requested_by.username}"
