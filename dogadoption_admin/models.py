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

    # 👇 ADD THIS
    violations = models.JSONField(
        blank=True,
        null=True,
        help_text="List of dog violations"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def claim_deadline(self):
        return self.rescued_date + timedelta(days=self.claim_days)

    def is_open_for_adoption(self):
        return timezone.now().date() > self.claim_deadline() and self.status not in ['reunited', 'adopted']

    def __str__(self):
        return f"Post by {self.user.username}"


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
