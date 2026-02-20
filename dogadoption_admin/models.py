from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta

class Post(models.Model):

    STATUS_CHOICES = [
        ('rescued', 'Rescued'),
        ('under_care', 'Under Care'),
        ('reunited', 'Reunited'),
        ('adopted', 'Adopted'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    caption = models.TextField()
    location = models.CharField(max_length=255, blank=True, null=True)

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='rescued'
    )

    rescued_date = models.DateField(default=timezone.now)

    claim_days = models.PositiveIntegerField(
        default=3,
        help_text="Days allowed for owner to claim dog"
    )

    violations = models.JSONField(
        blank=True,
        null=True,
        help_text="List of dog violations"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def claim_deadline(self):
        """Deadline for claim/adopt (created_at + claim_days)."""
        if self.created_at and self.claim_days:
            return self.created_at + timedelta(days=self.claim_days)
        return None

    def time_left(self):
        """
        Return remaining time until deadline.
        If no deadline, returns zero timedelta.
        """
        deadline = self.claim_deadline()
        if deadline:
            return deadline - timezone.now()
        return timedelta(seconds=0)

    def is_expired(self):
        """Return True if the current time is past the deadline."""
        deadline = self.claim_deadline()
        return deadline and timezone.now() > deadline

    def is_open_for_adoption(self):
        """
        True if still within the allowed claim/adopt window
        and not reunited or adopted.
        """
        return not self.is_expired() and self.status not in ['reunited', 'adopted']

    # Optional alias
    def is_open_for_claim_adopt(self):
        return self.is_open_for_adoption()



class PostImage(models.Model):
    post = models.ForeignKey(
        Post,
        related_name='images',
        on_delete=models.CASCADE
    )
    image = models.ImageField(upload_to='post_images/')

    def __str__(self):
        return f"Image for post {self.post.id}"

class PostRequest(models.Model):

    REQUEST_TYPE_CHOICES = [
        ('claim', 'Claim'),
        ('adopt', 'Adopt'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('rejected', 'Rejected'),
    ]

    post = models.ForeignKey(
        Post,
        related_name='requests',
        on_delete=models.CASCADE
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE)

    request_type = models.CharField(
        max_length=10,
        choices=REQUEST_TYPE_CHOICES
    )

    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default='pending'
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.request_type} ({self.status})"


class DogAnnouncement(models.Model):
    POST_TYPES = [
        ('COLOR', 'Plain Color with Text'),
        ('IMAGE_BG', 'Image Background with Text'),
        ('PHOTO', 'Standard Photo Post'),
    ]

    title = models.CharField(max_length=200)
    content = models.TextField()
    post_type = models.CharField(max_length=10, choices=POST_TYPES, default='COLOR')
    
    # Background options
    background_image = models.ImageField(upload_to='announcements/bg/', blank=True, null=True)
    background_color = models.CharField(max_length=20, default="#4f46e5", help_text="Hex code or Tailwind class")
    
    # For schedules (stored as a list of dicts: [{"time": "9am", "task": "Feeding"}])
    schedule_data = models.JSONField(blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)

    
    created_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="announcements")
    
    @property
    def like_count(self):
        return self.reactions.filter(reaction="LIKE").count()

    @property
    def love_count(self):
        return self.reactions.filter(reaction="LOVE").count()

    @property
    def wow_count(self):
        return self.reactions.filter(reaction="WOW").count()

    @property
    def sad_count(self):
        return self.reactions.filter(reaction="SAD").count()

    @property
    def angry_count(self):
        return self.reactions.filter(reaction="ANGRY").count()

    def __str__(self):
        return self.title
    
    
class AnnouncementReaction(models.Model):
    REACTION_CHOICES = [
        ('LIKE', '👍'),
        ('LOVE', '❤️'),
        ('WOW', '😮'),
        ('SAD', '😢'),
        ('ANGRY', '😡'),
    ]

    announcement = models.ForeignKey(
        DogAnnouncement,
        on_delete=models.CASCADE,
        related_name="reactions"
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    reaction = models.CharField(max_length=10, choices=REACTION_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('announcement', 'user')


class AnnouncementComment(models.Model):
    announcement = models.ForeignKey(
        DogAnnouncement,
        on_delete=models.CASCADE,
        related_name="comments"
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    comment = models.TextField()
    reply = models.TextField(blank=True, null=True)  # For admin replies
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self):
        return f"{self.user.username} - {self.comment[:20]}"

# models.py
class Dog(models.Model):
    date_registered = models.DateField()
    name = models.CharField(max_length=100)
    species = models.CharField(max_length=50, default="Canine")
    sex = models.CharField(max_length=1, choices=[('M', 'Male'), ('F', 'Female')])
    age = models.CharField(max_length=20, blank=True)  # e.g. "4 mos", "3 yrs"
    neutering_status = models.CharField(max_length=2, choices=[('No', 'No'), ('C', 'Castrated'), ('S', 'Spayed')], default='No')
    color = models.CharField(max_length=50, blank=True)
    owner_name = models.CharField(max_length=100)
    owner_address = models.TextField(blank=True)
    barangay = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return f"{self.name} ({self.species})"


#dog certification 
class CertificateSettings(models.Model):
    reg_no = models.CharField(max_length=50, default="REG-001")
    print_immediately = models.BooleanField(default=True)

    def __str__(self):
        return f"Certificate Settings ({self.reg_no})"


class DogRegistration(models.Model):
    SEX_CHOICES = (
        ('M', 'Male'),
        ('F', 'Female'),
    )

    STATUS_CHOICES = (
        ('Castrated', 'Castrated'),
        ('Spayed', 'Spayed'),
        ('Intact', 'Intact'),
    )

    reg_no = models.CharField(max_length=50)
    name_of_pet = models.CharField(max_length=100)
    breed = models.CharField(max_length=100)
    dob = models.DateField()
    color_markings = models.CharField(max_length=100)
    sex = models.CharField(max_length=1, choices=SEX_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)

    # Owner Personal Details
    owner_name = models.CharField(max_length=100)
    address = models.TextField()
    contact_no = models.CharField(max_length=20)

    date_registered = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name_of_pet} - {self.reg_no}"
