import os
from datetime import datetime, time, timedelta
from uuid import uuid4

from django.contrib.auth.models import User
from django.db import models
from django.db.models import DateTimeField, Exists, OuterRef, Subquery
from django.utils import timezone

class Post(models.Model):
    ADOPTION_DAYS = 3
    REQUEST_VERIFICATION_DAYS = 1
    BREED_OTHER = "other"
    COLOR_OTHER = "other"

    BREED_CHOICES = [
        ("aspin", "Aspin / Mixed Local Breed"),
        ("american_bully", "American Bully"),
        ("american_staffordshire_terrier", "American Staffordshire Terrier"),
        ("beagle", "Beagle"),
        ("belgian_malinois", "Belgian Malinois"),
        ("border_collie", "Border Collie"),
        ("boxer", "Boxer"),
        ("bull_terrier", "Bull Terrier"),
        ("chihuahua", "Chihuahua"),
        ("chow_chow", "Chow Chow"),
        ("cocker_spaniel", "Cocker Spaniel"),
        ("corgi", "Corgi"),
        ("dalmatian", "Dalmatian"),
        ("dachshund", "Dachshund"),
        ("doberman", "Doberman Pinscher"),
        ("french_bulldog", "French Bulldog"),
        ("german_shepherd", "German Shepherd"),
        ("golden_retriever", "Golden Retriever"),
        ("great_dane", "Great Dane"),
        ("husky", "Siberian Husky"),
        ("jack_russell_terrier", "Jack Russell Terrier"),
        ("japanese_spitz", "Japanese Spitz"),
        ("labrador", "Labrador Retriever"),
        ("maltese", "Maltese"),
        ("miniature_pinscher", "Miniature Pinscher"),
        ("pit_bull", "Pit Bull"),
        ("pomeranian", "Pomeranian"),
        ("poodle", "Poodle"),
        ("pug", "Pug"),
        ("rottweiler", "Rottweiler"),
        ("samoyed", "Samoyed"),
        ("schnauzer", "Schnauzer"),
        ("shih_tzu", "Shih Tzu"),
        ("yorkshire_terrier", "Yorkshire Terrier"),
        (BREED_OTHER, "Other"),
    ]

    AGE_GROUP_CHOICES = [
        ("puppy", "Puppy (< 1 year)"),
        ("young", "Young (1-3 years)"),
        ("adult", "Adult (3-8 years)"),
        ("senior", "Senior (8+ years)"),
    ]

    SIZE_GROUP_CHOICES = [
        ("small", "Small (up to 25 lbs)"),
        ("medium", "Medium (26-60 lbs)"),
        ("large", "Large (61-100 lbs)"),
        ("x_large", "X-Large (> 100 lbs)"),
    ]

    GENDER_CHOICES = [
        ("male", "Male"),
        ("female", "Female"),
    ]

    COAT_LENGTH_CHOICES = [
        ("short", "Short"),
        ("medium", "Medium"),
        ("long", "Long"),
        ("wire", "Wire"),
        ("hairless", "Hairless"),
        ("curly", "Curly"),
    ]

    COLOR_CHOICES = [
        ("black", "Black"),
        ("white", "White"),
        ("brown", "Brown"),
        ("chocolate", "Chocolate"),
        ("tan", "Tan"),
        ("cream", "Cream"),
        ("gold", "Gold"),
        ("gray", "Gray"),
        ("silver", "Silver"),
        ("blue", "Blue / Slate"),
        ("red", "Red"),
        ("orange", "Orange"),
        ("yellow", "Yellow"),
        ("fawn", "Fawn"),
        ("sable", "Sable"),
        ("apricot", "Apricot"),
        ("liver", "Liver"),
        ("lilac", "Lilac"),
        ("brindle", "Brindle"),
        ("merle", "Merle"),
        ("bicolor", "Bicolor"),
        ("tricolor", "Tricolor"),
        ("spotted", "Spotted"),
        ("patched", "Patched"),
        ("speckled", "Speckled / Ticked"),
        (COLOR_OTHER, "Other"),
    ]

    STATUS_CHOICES = [
        ('rescued', 'Rescued'),
        ('under_care', 'Under Care'),
        ('reunited', 'Reclaimed'),
        ('adopted', 'Adopted'),
    ]

    PHASE_OVERRIDE_CHOICES = [
        ("claim", "Redeem"),
        ("adopt", "Adoption"),
    ]
    MANUAL_PHASE_RESET_DAYS = 3

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    caption = models.TextField()
    breed = models.CharField(max_length=40, choices=BREED_CHOICES, blank=True, default="")
    breed_other = models.CharField(max_length=100, blank=True, default="")
    age_group = models.CharField(max_length=20, choices=AGE_GROUP_CHOICES, blank=True, default="")
    size_group = models.CharField(max_length=20, choices=SIZE_GROUP_CHOICES, blank=True, default="")
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES, blank=True, default="")
    coat_length = models.CharField(max_length=20, choices=COAT_LENGTH_CHOICES, blank=True, default="")
    colors = models.JSONField(blank=True, default=list)
    color_other = models.CharField(max_length=100, blank=True, default="")
    location = models.CharField(max_length=255, blank=True, null=True)

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='rescued'
    )

    rescued_date = models.DateField(blank=True, null=True)
    phase_override = models.CharField(
        max_length=10,
        choices=PHASE_OVERRIDE_CHOICES,
        blank=True,
        default="",
    )
    phase_override_started_at = models.DateTimeField(blank=True, null=True)
    is_history = models.BooleanField(default=False)
    is_pinned = models.BooleanField(default=False)
    pinned_at = models.DateTimeField(blank=True, null=True)
    view_count = models.PositiveIntegerField(default=0)

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

    @classmethod
    def with_pending_request_state(cls, queryset):
        pending_claim_qs = PostRequest.objects.filter(
            post_id=OuterRef("pk"),
            request_type="claim",
            status="pending",
        )
        pending_adopt_qs = PostRequest.objects.filter(
            post_id=OuterRef("pk"),
            request_type="adopt",
            status="pending",
        )
        return queryset.annotate(
            has_pending_claim_request=Exists(pending_claim_qs),
            has_pending_adopt_request=Exists(pending_adopt_qs),
            pending_claim_started_at=Subquery(
                pending_claim_qs.order_by("created_at").values("created_at")[:1],
                output_field=DateTimeField(),
            ),
            pending_claim_latest_at=Subquery(
                pending_claim_qs.order_by("-created_at").values("created_at")[:1],
                output_field=DateTimeField(),
            ),
            pending_adopt_started_at=Subquery(
                pending_adopt_qs.order_by("created_at").values("created_at")[:1],
                output_field=DateTimeField(),
            ),
            pending_adopt_latest_at=Subquery(
                pending_adopt_qs.order_by("-created_at").values("created_at")[:1],
                output_field=DateTimeField(),
            ),
        )

    @staticmethod
    def _clean_text(value):
        return " ".join((value or "").split()).strip()

    @property
    def display_breed(self):
        if self.breed == self.BREED_OTHER:
            return self._clean_text(self.breed_other) or "Other"
        if self.breed:
            return self.get_breed_display()
        return self._clean_text(self.caption)

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
    def display_title(self):
        return self.display_breed or self._clean_text(self.caption) or "Dog Listing"

    def _pending_request_details(self, request_type):
        flag_attr = f"has_pending_{request_type}_request"
        started_attr = f"pending_{request_type}_started_at"

        has_pending = getattr(self, flag_attr, None)
        started_at = getattr(self, started_attr, None)
        if has_pending is not None:
            return bool(has_pending), started_at

        prefetched_requests = getattr(self, "_prefetched_objects_cache", {}).get("requests")
        if prefetched_requests is not None:
            pending_created_ats = [
                req.created_at
                for req in prefetched_requests
                if req.status == "pending"
                and req.request_type == request_type
                and req.created_at
            ]
            return bool(pending_created_ats), min(pending_created_ats) if pending_created_ats else None

        started_at = self.requests.filter(
            status="pending",
            request_type=request_type,
        ).order_by("created_at").values_list("created_at", flat=True).first()
        return bool(started_at), started_at

    def _pending_request_created_bounds(self, request_type):
        flag_attr = f"has_pending_{request_type}_request"
        started_attr = f"pending_{request_type}_started_at"
        latest_attr = f"pending_{request_type}_latest_at"

        has_pending = getattr(self, flag_attr, None)
        started_at = getattr(self, started_attr, None)
        latest_at = getattr(self, latest_attr, None)
        if has_pending is not None:
            if not has_pending:
                return False, None, None
            return True, started_at, latest_at or started_at

        prefetched_requests = getattr(self, "_prefetched_objects_cache", {}).get("requests")
        if prefetched_requests is not None:
            pending_created_ats = [
                req.created_at
                for req in prefetched_requests
                if req.status == "pending"
                and req.request_type == request_type
                and req.created_at
            ]
            if not pending_created_ats:
                return False, None, None
            return True, min(pending_created_ats), max(pending_created_ats)

        pending_qs = self.requests.filter(
            status="pending",
            request_type=request_type,
        )
        started_at = pending_qs.order_by("created_at").values_list("created_at", flat=True).first()
        if not started_at:
            return False, None, None
        latest_at = pending_qs.order_by("-created_at").values_list("created_at", flat=True).first()
        return True, started_at, latest_at or started_at

    @property
    def pending_review_request_type(self):
        if self.status in ["reunited", "adopted"]:
            return None

        claim_pending, _ = self._pending_request_details("claim")
        if claim_pending:
            return "claim"

        adopt_pending, _ = self._pending_request_details("adopt")
        if adopt_pending:
            return "adopt"

        return None

    @property
    def pending_review_started_at(self):
        request_type = self.pending_review_request_type
        if not request_type:
            return None
        return self._pending_request_details(request_type)[1]

    @property
    def pending_review_until(self):
        started_at = self.pending_review_started_at
        if not started_at:
            return None
        return self.pending_request_review_available_at(self.pending_review_request_type)

    @property
    def has_pending_review(self):
        return bool(self.pending_review_request_type)

    def pending_request_review_available_at(self, request_type):
        if request_type not in {"claim", "adopt"}:
            return None

        has_pending, _, latest_created_at = self._pending_request_created_bounds(request_type)
        if not has_pending:
            return None

        schedule = self._timeline_schedule()
        if schedule["use_calendar_schedule"]:
            if request_type == "claim":
                required_days = max(int(self.claim_days or 0), 0)
                schedule_dates = schedule["claim_dates"]
            else:
                required_days = self.ADOPTION_DAYS
                schedule_dates = schedule["adoption_dates"]

            if len(schedule_dates) < required_days:
                return None

        ready_candidates = []
        if latest_created_at:
            ready_candidates.append(latest_created_at + PostRequest.verification_window())

        phase_deadline = self.claim_deadline() if request_type == "claim" else self.adoption_deadline()
        if phase_deadline:
            ready_candidates.append(phase_deadline)

        return max(ready_candidates) if ready_candidates else None

    @classmethod
    def active_appointment_dates(cls):
        return list(
            GlobalAppointmentDate.objects.filter(is_active=True)
            .order_by("appointment_date")
            .values_list("appointment_date", flat=True)
        )

    @classmethod
    def attach_active_appointment_dates(cls, posts, appointment_dates=None):
        dates = list(
            appointment_dates
            if appointment_dates is not None
            else cls.active_appointment_dates()
        )
        for post in posts or []:
            setattr(post, "_prefetched_global_appointment_dates", dates)
        return dates

    @staticmethod
    def _schedule_deadline_for_date(schedule_date):
        if not schedule_date:
            return None
        deadline = datetime.combine(schedule_date, time.max)
        if timezone.is_naive(deadline):
            deadline = timezone.make_aware(
                deadline,
                timezone.get_current_timezone(),
            )
        return deadline

    @staticmethod
    def _schedule_day_start(schedule_date):
        if not schedule_date:
            return None
        day_start = datetime.combine(schedule_date, time.min)
        if timezone.is_naive(day_start):
            day_start = timezone.make_aware(
                day_start,
                timezone.get_current_timezone(),
            )
        return day_start

    @classmethod
    def _schedule_day_end_exclusive(cls, schedule_date):
        day_start = cls._schedule_day_start(schedule_date)
        if not day_start:
            return None
        return day_start + timedelta(days=1)

    @classmethod
    def _remaining_scheduled_time(cls, schedule_dates, now):
        remaining = timedelta(seconds=0)
        for schedule_date in schedule_dates or []:
            day_start = cls._schedule_day_start(schedule_date)
            day_end = cls._schedule_day_end_exclusive(schedule_date)
            if not day_start or not day_end or now >= day_end:
                continue
            remaining += day_end - max(now, day_start)
        return remaining

    @classmethod
    def _scheduled_window_active(cls, schedule_dates, now):
        return cls._remaining_scheduled_time(schedule_dates, now) > timedelta(seconds=0)

    def _legacy_claim_deadline(self):
        if self.created_at and self.claim_days is not None:
            claim_days = max(int(self.claim_days), 0)
            return self.created_at + timedelta(days=claim_days)
        return None

    def _manual_appointment_dates(self, started_at):
        active_dates = getattr(self, "_prefetched_global_appointment_dates", None)
        if active_dates is None:
            active_dates = self.active_appointment_dates()
        else:
            active_dates = list(active_dates)

        eligible_dates = []
        for schedule_date in active_dates:
            day_end = self._schedule_day_end_exclusive(schedule_date)
            if day_end and day_end > started_at:
                eligible_dates.append(schedule_date)
        return eligible_dates

    def _manual_phase_schedule(self, now=None):
        if self.status in ["reunited", "adopted"]:
            return {
                "is_active": False,
                "current_phase": "closed",
                "use_calendar_schedule": False,
                "claim_dates": [],
                "adoption_dates": [],
                "claim_deadline": None,
                "adoption_deadline": None,
            }

        phase = (self.phase_override or "").strip()
        started_at = self.phase_override_started_at
        if phase not in {"claim", "adopt"} or not started_at:
            return {
                "is_active": False,
                "current_phase": "",
                "use_calendar_schedule": False,
                "claim_dates": [],
                "adoption_dates": [],
                "claim_deadline": None,
                "adoption_deadline": None,
            }

        now = now or timezone.now()
        manual_phase_days = self.MANUAL_PHASE_RESET_DAYS
        use_calendar_schedule = False
        claim_dates = []
        adoption_dates = []
        claim_deadline = None
        adoption_deadline = None
        current_phase = "closed"

        eligible_dates = self._manual_appointment_dates(started_at)
        if eligible_dates:
            use_calendar_schedule = True
            if phase == "claim":
                claim_dates = eligible_dates[:manual_phase_days]
                adoption_dates = eligible_dates[
                    manual_phase_days:manual_phase_days + manual_phase_days
                ]
            else:
                adoption_dates = eligible_dates[:manual_phase_days]

            if claim_dates:
                claim_deadline = self._schedule_deadline_for_date(claim_dates[-1])
            if adoption_dates:
                adoption_deadline = self._schedule_deadline_for_date(adoption_dates[-1])

            if phase == "claim" and self._scheduled_window_active(claim_dates, now):
                current_phase = "claim"
            elif self._scheduled_window_active(adoption_dates, now):
                current_phase = "adopt"
        else:
            reset_delta = timedelta(days=manual_phase_days)
            if phase == "claim":
                claim_deadline = started_at + reset_delta
                adoption_deadline = claim_deadline + reset_delta
                if now <= claim_deadline:
                    current_phase = "claim"
                elif now <= adoption_deadline:
                    current_phase = "adopt"
            else:
                adoption_deadline = started_at + reset_delta
                if now <= adoption_deadline:
                    current_phase = "adopt"

        return {
            "is_active": current_phase in {"claim", "adopt"},
            "current_phase": current_phase,
            "use_calendar_schedule": use_calendar_schedule,
            "claim_dates": claim_dates,
            "adoption_dates": adoption_dates,
            "claim_deadline": claim_deadline,
            "adoption_deadline": adoption_deadline,
        }

    def _timeline_schedule(self):
        active_dates = getattr(self, "_prefetched_global_appointment_dates", None)
        if active_dates is None:
            active_dates = self.active_appointment_dates()
        else:
            active_dates = list(active_dates)

        start_date = None
        if self.created_at:
            start_date = (
                timezone.localtime(self.created_at).date()
                if timezone.is_aware(self.created_at)
                else self.created_at.date()
            )

        claim_days = max(int(self.claim_days or 0), 0)
        eligible_dates = (
            [day for day in active_dates if day >= start_date]
            if start_date
            else []
        )
        cache_key = (
            self.created_at,
            claim_days,
            tuple(active_dates),
            tuple(eligible_dates),
        )
        cached = getattr(self, "_timeline_schedule_cache", None)
        if cached and cached.get("key") == cache_key:
            return cached["value"]

        use_calendar_schedule = bool(active_dates)
        claim_dates = []
        adoption_dates = []

        if use_calendar_schedule:
            if claim_days:
                claim_dates = eligible_dates[:claim_days]
            adoption_start = claim_days
            adoption_dates = eligible_dates[
                adoption_start: adoption_start + self.ADOPTION_DAYS
            ]

        claim_deadline = (
            self._schedule_deadline_for_date(claim_dates[-1])
            if use_calendar_schedule and claim_dates
            else (
                self._legacy_claim_deadline()
                if not use_calendar_schedule
                else None
            )
        )
        adoption_deadline = (
            self._schedule_deadline_for_date(adoption_dates[-1])
            if use_calendar_schedule and adoption_dates
            else (
                claim_deadline + timedelta(days=self.ADOPTION_DAYS)
                if (not use_calendar_schedule and claim_deadline)
                else None
            )
        )

        schedule = {
            "use_calendar_schedule": use_calendar_schedule,
            "claim_dates": claim_dates,
            "adoption_dates": adoption_dates,
            "claim_deadline": claim_deadline,
            "adoption_deadline": adoption_deadline,
        }
        self._timeline_schedule_cache = {
            "key": cache_key,
            "value": schedule,
        }
        return schedule

    def claim_deadline(self):
        """Deadline for owner claim window."""
        manual_schedule = self._manual_phase_schedule()
        if self.phase_override == "claim" and manual_schedule["claim_deadline"]:
            return manual_schedule["claim_deadline"]
        return self._timeline_schedule()["claim_deadline"]

    def adoption_deadline(self):
        """Deadline for adoption window after the claim window ends."""
        manual_schedule = self._manual_phase_schedule()
        if self.phase_override in {"claim", "adopt"} and manual_schedule["adoption_deadline"]:
            return manual_schedule["adoption_deadline"]
        return self._timeline_schedule()["adoption_deadline"]

    def _phase_schedule_dates(self, phase):
        schedule = self._timeline_schedule()
        if phase == "claim":
            return schedule["claim_dates"]
        if phase == "adopt":
            return schedule["adoption_dates"]
        return []

    def _phase_schedule_complete(self, phase, now=None):
        now = now or timezone.now()
        schedule = self._timeline_schedule()
        if not schedule["use_calendar_schedule"]:
            deadline = (
                schedule["claim_deadline"]
                if phase == "claim"
                else schedule["adoption_deadline"]
            )
            return bool(deadline and now > deadline)

        if phase == "claim":
            required_days = max(int(self.claim_days or 0), 0)
            schedule_dates = schedule["claim_dates"]
        elif phase == "adopt":
            required_days = self.ADOPTION_DAYS
            schedule_dates = schedule["adoption_dates"]
        else:
            return True

        if required_days <= 0:
            return True
        if len(schedule_dates) < required_days:
            return False

        return all(
            now >= self._schedule_day_end_exclusive(schedule_date)
            for schedule_date in schedule_dates
        )

    def timeline_phase(self, now=None):
        if self.status in ["reunited", "adopted"]:
            return "closed"

        now = now or timezone.now()
        schedule = self._timeline_schedule()
        if schedule["use_calendar_schedule"]:
            if not self._phase_schedule_complete("claim", now):
                return "claim"
            if not self._phase_schedule_complete("adopt", now):
                return "adopt"
            return "closed"

        claim_end = schedule["claim_deadline"]
        adopt_end = schedule["adoption_deadline"]

        if claim_end and now <= claim_end:
            return "claim"
        if adopt_end and now <= adopt_end:
            return "adopt"
        return "closed"

    def current_phase(self, now=None):
        """
        Returns one of:
        - claim
        - adopt
        - closed
        """
        now = now or timezone.now()
        manual_schedule = self._manual_phase_schedule(now)
        if self.phase_override in {"claim", "adopt"} and manual_schedule["current_phase"]:
            return manual_schedule["current_phase"]
        if self.phase_override in {"claim", "adopt"} and not manual_schedule["is_active"]:
            return "closed"
        return self.timeline_phase(now)

    def time_left(self, now=None):
        """Return remaining time in the active phase."""
        now = now or timezone.now()
        manual_schedule = self._manual_phase_schedule(now)
        if self.phase_override in {"claim", "adopt"}:
            if manual_schedule["current_phase"] == "claim":
                if manual_schedule["use_calendar_schedule"]:
                    return self._remaining_scheduled_time(manual_schedule["claim_dates"], now)
                if manual_schedule["claim_deadline"]:
                    return max(manual_schedule["claim_deadline"] - now, timedelta(seconds=0))
            if manual_schedule["current_phase"] == "adopt":
                if manual_schedule["use_calendar_schedule"]:
                    return self._remaining_scheduled_time(manual_schedule["adoption_dates"], now)
                if manual_schedule["adoption_deadline"]:
                    return max(manual_schedule["adoption_deadline"] - now, timedelta(seconds=0))
            return timedelta(seconds=0)

        phase = self.current_phase(now)
        schedule = self._timeline_schedule()

        if phase == 'claim':
            if schedule["use_calendar_schedule"]:
                return self._remaining_scheduled_time(schedule["claim_dates"], now)
            claim_deadline = schedule["claim_deadline"]
            return max(claim_deadline - now, timedelta(seconds=0)) if claim_deadline else timedelta(seconds=0)
        if phase == 'adopt':
            if schedule["use_calendar_schedule"]:
                return self._remaining_scheduled_time(schedule["adoption_dates"], now)
            adoption_deadline = schedule["adoption_deadline"]
            return max(adoption_deadline - now, timedelta(seconds=0)) if adoption_deadline else timedelta(seconds=0)
        return timedelta(seconds=0)

    def is_expired(self):
        """Return True if both claim and adoption windows are finished."""
        if self.status in ["reunited", "adopted"] or self.has_pending_review:
            return False
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

    def save(self, *args, **kwargs):
        if not isinstance(self.colors, list):
            self.colors = [self.colors] if self.colors else []
        breed_label = self.display_breed
        if breed_label:
            self.caption = breed_label
        elif self.caption is None:
            self.caption = ""
        super().save(*args, **kwargs)

    class Meta:
        indexes = [
            models.Index(fields=["created_at"], name="post_created_idx"),
            models.Index(fields=["status", "created_at"], name="post_status_created_idx"),
            models.Index(fields=["is_history", "status", "created_at"], name="post_hist_status_created_idx"),
            models.Index(fields=["is_pinned", "is_history", "created_at"], name="post_pin_hist_created_idx"),
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
    VERIFICATION_WINDOW_DAYS = 1

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
            models.Index(fields=["request_type", "status", "created_at"], name="postreq_type_status_cr_idx"),
            models.Index(fields=["user", "request_type", "status"], name="postreq_user_type_status_idx"),
        ]

    @classmethod
    def verification_window(cls):
        return timedelta(days=cls.VERIFICATION_WINDOW_DAYS)

    @property
    def approval_available_at(self):
        if self.status != "pending":
            return None
        post = getattr(self, "post", None)
        if self.post_id and post is None:
            post = self.post
        if post is not None:
            return post.pending_request_review_available_at(self.request_type)
        if not self.created_at:
            return None
        return self.created_at + self.verification_window()

    @property
    def verification_ready(self):
        approval_at = self.approval_available_at
        if self.status != "pending" or not approval_at:
            return False
        return timezone.now() >= approval_at

    @property
    def verification_pending(self):
        approval_at = self.approval_available_at
        if self.status != "pending" or not approval_at:
            return False
        return timezone.now() < approval_at

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
class StaffAccess(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="staff_access",
    )
    can_create_posts = models.BooleanField(default=False)
    can_view_post_history = models.BooleanField(default=False)
    can_view_status_cards = models.BooleanField(default=False)
    can_manage_capture_requests = models.BooleanField(default=False)
    can_access_registration = models.BooleanField(default=False)
    can_access_registration_list = models.BooleanField(default=False)
    can_access_vaccination = models.BooleanField(default=False)
    can_access_vaccination_list = models.BooleanField(default=False)
    can_access_citations = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Staff access"
        verbose_name_plural = "Staff access"

    def __str__(self):
        return f"Staff access for {self.user.username}"


class DogAnnouncement(models.Model):
    CATEGORY_DOG_ANNOUNCEMENT = "DOG_ANNOUNCEMENT"
    CATEGORY_DOG_LAW = "DOG_LAW"
    CATEGORY_CHOICES = [
        (CATEGORY_DOG_ANNOUNCEMENT, "Dog Announcements"),
        (CATEGORY_DOG_LAW, "Dog Laws"),
    ]
    BUCKET_ORDINARY = "ordinary"
    BUCKET_PINNED = "pinned"
    BUCKET_CAMPAIGN = "campaign"
    DISPLAY_BUCKET_CHOICES = [
        (BUCKET_ORDINARY, "Ordinary"),
        (BUCKET_PINNED, "Pinned"),
        (BUCKET_CAMPAIGN, "Education"),
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
    display_bucket = models.CharField(
        max_length=16,
        choices=DISPLAY_BUCKET_CHOICES,
        default=BUCKET_ORDINARY,
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
            models.Index(fields=["display_bucket", "created_at"], name="dogann_bucket_created_idx"),
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


class AnnouncementReaction(models.Model):
    announcement = models.ForeignKey(
        DogAnnouncement,
        on_delete=models.CASCADE,
        related_name="reactions",
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["announcement", "user"],
                name="annreaction_unique_user_per_announcement",
            ),
        ]
        indexes = [
            models.Index(fields=["announcement"], name="annreaction_announcement_idx"),
            models.Index(fields=["user", "created_at"], name="annreaction_user_created_idx"),
        ]

    def __str__(self):
        return f"{self.user.username} reacted to announcement {self.announcement_id}"


class AdminNotification(models.Model):
    title = models.CharField(max_length=160)
    message = models.TextField(blank=True)
    url = models.CharField(max_length=255, blank=True)
    event_key = models.CharField(max_length=255, blank=True, default="", db_index=True)
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
    owner_name_key = models.CharField(max_length=120, blank=True, default="", db_index=True)
    owner_user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="registered_dogs",
    )
    owner_address = models.TextField(blank=True)
    barangay = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        indexes = [
            models.Index(fields=["date_registered"], name="dog_date_reg_idx"),
            models.Index(fields=["barangay", "date_registered"], name="dog_brgy_date_idx"),
            models.Index(fields=["owner_user", "date_registered"], name="dog_owneruser_date_idx"),
            models.Index(fields=["owner_name_key", "date_registered"], name="dog_ownerkey_date_idx"),
        ]

    def __str__(self):
        return f"{self.name} ({self.species})"


def dog_registration_image_upload_to(instance, filename):
    _, ext = os.path.splitext(filename or "")
    extension = ext.lower() if ext else ".jpg"
    return (
        f"dog_registrations/{instance.dog_id}/"
        f"{timezone.now():%Y/%m}/{uuid4().hex}{extension}"
    )


class DogImage(models.Model):
    dog = models.ForeignKey(
        Dog,
        on_delete=models.CASCADE,
        related_name="images",
    )
    image = models.ImageField(upload_to=dog_registration_image_upload_to)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["dog", "created_at"], name="dogimg_dog_created_idx"),
            models.Index(fields=["created_at"], name="dogimg_created_idx"),
        ]

    def __str__(self):
        return f"Dog {self.dog_id} image {self.id}"


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
    medicine_expiry_date = models.DateField(null=True, blank=True)
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
    owner_first_name = models.CharField(max_length=150, blank=True, default="")
    owner_last_name = models.CharField(max_length=150, blank=True, default="")
    owner_barangay = models.CharField(max_length=255, blank=True, default="")

    penalty = models.ForeignKey(Penalty, on_delete=models.CASCADE)
    penalties = models.ManyToManyField(Penalty, related_name='citations', blank=True)
    date_issued = models.DateTimeField(auto_now_add=True)
    remarks = models.TextField(blank=True)

    def __str__(self):
        return f"Citation #{self.id} - {self.owner}"


class UserViolationSummary(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="violation_summary",
    )
    violation_count = models.PositiveIntegerField(default=0, db_index=True)
    latest_notification = models.ForeignKey(
        "UserViolationNotification",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["violation_count", "updated_at"], name="usrviolsum_count_upd_idx"),
        ]

    def __str__(self):
        return f"Violation summary for {self.user.username}"


class UserViolationNotification(models.Model):
    STATUS_GENERATED = "generated"
    STATUS_PRINTED = "printed"
    LETTER_STATUS_CHOICES = [
        (STATUS_GENERATED, "Generated"),
        (STATUS_PRINTED, "Printed"),
    ]

    summary = models.ForeignKey(
        UserViolationSummary,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    trigger_violation_count = models.PositiveIntegerField(default=3)
    title = models.CharField(max_length=160)
    message = models.TextField()
    letter_status = models.CharField(
        max_length=20,
        choices=LETTER_STATUS_CHOICES,
        default=STATUS_GENERATED,
    )
    admin_notification = models.OneToOneField(
        AdminNotification,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="user_violation_notification",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    printed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["summary", "trigger_violation_count"],
                name="usrviolnotif_unique_sum_count",
            ),
        ]
        indexes = [
            models.Index(fields=["letter_status", "created_at"], name="usrviolnotif_status_cr_idx"),
        ]

    def __str__(self):
        return f"{self.title} ({self.summary.user.username})"
