from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta

class Post(models.Model):
    ADOPTION_DAYS = 3

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

    rescued_date = models.DateField(blank=True, null=True)

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
        """Deadline for owner claim window."""
        if self.created_at and self.claim_days:
            return self.created_at + timedelta(days=self.claim_days)
        return None

    def adoption_deadline(self):
        """Deadline for adoption window (claim deadline + fixed 3 days)."""
        claim_end = self.claim_deadline()
        if claim_end:
            return claim_end + timedelta(days=self.ADOPTION_DAYS)
        return None

    def current_phase(self):
        """
        Returns one of:
        - claim
        - adopt
        - closed
        """
        if self.status in ['reunited', 'adopted']:
            return 'closed'

        now = timezone.now()
        claim_end = self.claim_deadline()
        adopt_end = self.adoption_deadline()

        if claim_end and now <= claim_end:
            return 'claim'
        if adopt_end and now <= adopt_end:
            return 'adopt'
        return 'closed'

    def time_left(self):
        """Return remaining time in the active phase."""
        phase = self.current_phase()
        now = timezone.now()

        if phase == 'claim':
            return self.claim_deadline() - now
        if phase == 'adopt':
            return self.adoption_deadline() - now
        return timedelta(seconds=0)

    def is_expired(self):
        """Return True if both claim and adoption windows are finished."""
        deadline = self.adoption_deadline()
        return deadline and timezone.now() > deadline

    def is_open_for_adoption(self):
        """True only during adoption phase."""
        return self.current_phase() == 'adopt'

    def is_open_for_claim(self):
        """True only during claim phase."""
        return self.current_phase() == 'claim'

    # Optional alias
    def is_open_for_claim_adopt(self):
        return self.current_phase() in ['claim', 'adopt']

    class Meta:
        indexes = [
            models.Index(fields=["created_at"], name="post_created_idx"),
            models.Index(fields=["status", "created_at"], name="post_status_created_idx"),
        ]



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
        'Post',
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
    appointment_date = models.DateField(
        null=True,
        blank=True,
        help_text="Preferred date selected by the user."
    )
    scheduled_appointment_date = models.DateField(
        null=True,
        blank=True,
        help_text="Final appointment date assigned by admin."
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["post", "request_type", "status"], name="postreq_post_type_status_idx"),
            models.Index(fields=["request_type", "status", "created_at"], name="postreq_type_status_created_idx"),
            models.Index(fields=["user", "request_type", "status"], name="postreq_user_type_status_idx"),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.request_type} ({self.status})"


class GlobalAppointmentDate(models.Model):
    appointment_date = models.DateField(unique=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='created_global_appointment_dates'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['appointment_date']
        indexes = [
            models.Index(fields=["is_active", "appointment_date"], name="gappt_active_date_idx"),
        ]

    def __str__(self):
        return f"Global appointment - {self.appointment_date}"


# ✅ CLEAN ANNOUNCEMENT MODEL (NO REACTIONS)
class DogAnnouncement(models.Model):
    CATEGORY_DOG_ANNOUNCEMENT = "DOG_ANNOUNCEMENT"
    CATEGORY_DOG_LAW = "DOG_LAW"
    CATEGORY_CHOICES = [
        (CATEGORY_DOG_ANNOUNCEMENT, "Dog Announcements"),
        (CATEGORY_DOG_LAW, "Dog Laws"),
    ]

    POST_TYPES = [
        ('COLOR', 'Plain Color with Text'),
        ('IMAGE_BG', 'Image Background with Text'),
        ('PHOTO', 'Standard Photo Post'),
    ]

    title = models.CharField(max_length=200)
    content = models.TextField()
    category = models.CharField(
        max_length=40,
        choices=CATEGORY_CHOICES,
        default=CATEGORY_DOG_ANNOUNCEMENT
    )

    # Background options
    background_image = models.ImageField(
        upload_to='announcements/bg/',
        blank=True,
        null=True
    )

    background_color = models.CharField(
        max_length=20,
        default="#eeedf3"
    )

    # Optional schedule
    schedule_data = models.JSONField(
        blank=True,
        null=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    created_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="announcements"
    )

    class Meta:
        indexes = [
            models.Index(fields=["created_at"], name="dogann_created_idx"),
            models.Index(fields=["category", "created_at"], name="dogann_category_created_idx"),
        ]

    def __str__(self):
        return self.title


class DogAnnouncementImage(models.Model):
    announcement = models.ForeignKey(
        DogAnnouncement,
        on_delete=models.CASCADE,
        related_name="images",
    )
    image = models.ImageField(upload_to="announcements/photos/")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"Announcement {self.announcement_id} image {self.id}"


# Dog catcher contact numbers for SMS notifications
class DogCatcherContact(models.Model):
    name = models.CharField(max_length=120, blank=True)
    phone_number = models.CharField(max_length=32)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        label = self.name.strip() if self.name else "Dog Catcher"
        return f"{label} ({self.phone_number})"


#  COMMENTS ONLY (NO REACTIONS)
class AnnouncementComment(models.Model):

    announcement = models.ForeignKey(
        DogAnnouncement,
        on_delete=models.CASCADE,
        related_name="comments"
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE)

    comment = models.TextField()

    reply = models.TextField(
        blank=True,
        null=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["announcement", "created_at"], name="anncomment_ann_created_idx"),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.comment[:20]}"


class AdminNotification(models.Model):
    title = models.CharField(max_length=160)
    message = models.TextField(blank=True)
    url = models.CharField(max_length=255, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=["is_read", "created_at"], name="adminnotif_read_created_idx"),
        ]

    def __str__(self):
        return self.title


class Barangay(models.Model):
    name = models.CharField(max_length=100, unique=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


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
    default_vac_date = models.DateField(null=True, blank=True)
    default_vaccine_name = models.CharField(max_length=255, blank=True, default="")
    default_manufacturer_lot_no = models.CharField(max_length=255, blank=True, default="")
    default_vaccine_expiry_date = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"Certificate Settings ({self.reg_no})"


class DogRegistration(models.Model):
    SEX_CHOICES = (
        ('M', 'Male'),
        ('F', 'Female'),
    )

    STATUS_CHOICES = (
        ('None', 'None'),
        ('Castrated', 'Castrated'),
        ('Spayed', 'Spayed'),
        ('Intact', 'Intact'),
    )

    reg_no = models.CharField(max_length=50)
    name_of_pet = models.CharField(max_length=100)
    breed = models.CharField(max_length=100)
    dob = models.DateField(null=True, blank=True)
    color_markings = models.CharField(max_length=100)
    sex = models.CharField(max_length=1, choices=SEX_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)

    # Owner Personal Details
    owner_name = models.CharField(max_length=100)
    address = models.TextField()
    contact_no = models.CharField(max_length=20)

    date_registered = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["date_registered"], name="dogreg_date_registered_idx"),
        ]

    def __str__(self):
        return f"{self.name_of_pet} - {self.reg_no}"


#for deworming and vaccination records
class Pet(models.Model):
    PET_TYPE_CHOICES = (
        ('Dog', 'Dog'),
        ('Cat', 'Cat'),
    )

    name = models.CharField(max_length=100)
    pet_type = models.CharField(max_length=10, choices=PET_TYPE_CHOICES)

    def __str__(self):
        return f"{self.name} ({self.pet_type})"


class VaccinationRecord(models.Model):
    registration = models.ForeignKey(
        DogRegistration,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="vaccinations"
    )
    date = models.DateField()
    vaccine_name = models.CharField(max_length=255)
    manufacturer_lot_no = models.CharField(max_length=255, blank=True, default="")
    vaccine_expiry_date = models.DateField()
    vaccination_expiry_date = models.DateField()
    veterinarian = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.registration.name_of_pet} - {self.vaccine_name}"

class DewormingTreatmentRecord(models.Model):
    registration = models.ForeignKey(
        DogRegistration,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="dewormings"
    )
    date = models.DateField()
    medicine_given = models.CharField(max_length=255)
    route = models.CharField(max_length=255)
    frequency = models.CharField(max_length=255)
    veterinarian = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.registration.name_of_pet} - {self.medicine_given}"
    
class PenaltySection(models.Model):
    number = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ['number']

    def __str__(self):
        return f"Section {self.number}"
    
class Penalty(models.Model):
    section = models.ForeignKey(
        PenaltySection,
        on_delete=models.CASCADE,
        related_name="penalties",
    )
    number = models.PositiveIntegerField()
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['section', 'number']
        unique_together = ('section', 'number')

    def __str__(self):
        return f"{self.section} - {self.number}"
    
class Citation(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)

    penalty = models.ForeignKey(Penalty, on_delete=models.CASCADE)
    penalties = models.ManyToManyField(Penalty, related_name='citations', blank=True)
    date_issued = models.DateTimeField(auto_now_add=True)
    remarks = models.TextField(blank=True)

    def __str__(self):
        return f"Citation #{self.id} - {self.owner}"
