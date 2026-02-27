from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import user_passes_test
from django.views.decorators.http import require_POST
from django.db.models import Count, Q
from datetime import timedelta
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from datetime import datetime
from django.contrib import messages
from django.conf import settings
from django.http import JsonResponse

from django.contrib.auth.models import User
from django.views.decorators.http import require_http_methods
from functools import wraps
import json



from django.http import HttpResponse


import io
from io import BytesIO


from django.template.loader import render_to_string
from django.views.decorators.csrf import csrf_exempt

from reportlab.platypus import Paragraph, Spacer
from openpyxl import Workbook
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
import pandas as pd
from reportlab.platypus import SimpleDocTemplate, Table
from docx import Document
from openpyxl import Workbook
from xhtml2pdf import pisa
from docx import Document





#forms.py
from .forms import PostForm
from .forms import PenaltyForm, SectionForm,CitationForm


#models in admin 
from .models import Post, PostImage , DogAnnouncement, AnnouncementComment, PostRequest
from .models import DogCatcherContact, AdminNotification
from .models import Citation
from .models import Post, PostImage, PostRequest
from .models import Penalty, PenaltySection
from .models import Dog
from .models import DogRegistration, CertificateSettings
from .models import Pet, VaccinationRecord, DewormingTreatmentRecord


#models from users
from user.models import Profile,FaceImage 
from user.models import DogCaptureRequest, AdoptionRequest,FaceImage, Profile,OwnerClaim, ClaimImage

from .sms import build_capture_message, send_sms



# views.py


# ADMIN-ONLY DECORATOR
def admin_required(view_func):
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_staff:
            return redirect('user:login')
        return view_func(request, *args, **kwargs)
    return wrapper

# AUTH VIEWS

def admin_login(request):
    return redirect('user:login')


@login_required
def admin_logout(request):
    logout(request)
    response = redirect('user:login')
    response.delete_cookie('admin_sessionid')
    return response


# ===================       HOMEPAGE OF THE ADMIN        ===================

# CREATE POST
@admin_required
def create_post(request):
    if request.method == 'POST':
        post_form = PostForm(request.POST)

        if post_form.is_valid():
            post = post_form.save(commit=False)
            post.user = request.user
            post.save()

            # Multiple images
            for image in request.FILES.getlist('images'):
                PostImage.objects.create(post=post, image=image)

            messages.success(request, "Post created successfully.")
            return redirect('dogadoption_admin:post_list')
    else:
        post_form = PostForm()

    return render(request, 'admin_home/create_post.html', {
        'post_form': post_form
    })


# POST LIST WITH DROPDOWN FILTER
@admin_required
def post_list(request):
    status_filter = request.GET.get('status', 'all')

    # Base queryset with annotation
    base_qs = Post.objects.annotate(
        claim_count=Count('requests', filter=Q(requests__request_type='claim', requests__status='pending')),
        adopt_count=Count('requests', filter=Q(requests__request_type='adopt', requests__status='pending'))
    )

    # FILTER
    if status_filter == 'ready':
        # Only posts still within time window & not reunited/adopted
        posts = [p for p in base_qs if p.is_open_for_claim_adopt()]
    elif status_filter == 'reunited':
        posts = base_qs.filter(status='reunited')
    elif status_filter == 'adopted':
        posts = base_qs.filter(status='adopted')
    else:
        posts = base_qs  # All

    # Calculate days/hours/minutes left
    enriched = []
    now = timezone.now()

    for p in posts:
        days = hours = minutes = 0
        phase = p.current_phase()

        if phase in ['claim', 'adopt']:
            diff = p.time_left()
            total_seconds = max(int(diff.total_seconds()), 0)

            days = total_seconds // 86400
            remainder = total_seconds % 86400
            hours = remainder // 3600
            remainder = remainder % 3600
            minutes = remainder // 60

        enriched.append({
            'post': p,
            'days_left': days,
            'hours_left': hours,
            'minutes_left': minutes,
            'phase': phase,
        })

    # Sort by newest
    enriched.sort(key=lambda x: x['post'].created_at, reverse=True)

    return render(request, 'admin_home/post_list.html', {
        'posts': enriched,
        'current_filter': status_filter,
    })

#   CLAIM REQUESTS
@admin_required
def claim_requests(request, post_id):
    post = get_object_or_404(Post, id=post_id)

    claims = post.requests.filter(request_type='claim') \
                          .select_related('user') \
                          .prefetch_related('images')

    user_ids = [req.user.id for req in claims]
    profiles = Profile.objects.filter(user_id__in=user_ids)
    faceauth = FaceImage.objects.filter(user_id__in=user_ids)

    requests_with_meta = []
    for req in claims:
        profile = profiles.filter(user_id=req.user.id).first()
        face_images = faceauth.filter(user_id=req.user.id)
        requests_with_meta.append({
            'req': req,
            'profile': profile,
            'face_images': face_images
        })

    return render(request, 'admin_claim/claim_requests.html', {
        'post': post,
        'requests_meta': requests_with_meta
    })


# ADOPTION REQUESTS
@admin_required
def adoption_requests(request, post_id):
    post = get_object_or_404(Post, id=post_id)

    adoptions = post.requests.filter(request_type='adopt') \
                             .select_related('user') \
                             .prefetch_related('images')

    user_ids = [req.user.id for req in adoptions]
    profiles = Profile.objects.filter(user_id__in=user_ids)
    faceauth = FaceImage.objects.filter(user_id__in=user_ids)

    requests_with_meta = []
    for req in adoptions:
        profile = profiles.filter(user_id=req.user.id).first()
        face_images = faceauth.filter(user_id=req.user.id)
        requests_with_meta.append({
            'req': req,
            'profile': profile,
            'face_images': face_images
        })

    return render(request, 'admin_adoption/adoption_request.html', {
        'post': post,
        'requests_meta': requests_with_meta
    })


# ACCEPT / REJECT REQUEST
@admin_required
def update_request(request, req_id, action):
    req = get_object_or_404(PostRequest, id=req_id)
    post = req.post

    if action == 'accept':
        req.status = 'accepted'

        #  Move post automatically
        if req.request_type == 'claim':
            post.status = 'reunited'
        elif req.request_type == 'adopt':
            post.status = 'adopted'

        post.save()

        # Auto reject others
        post.requests.exclude(id=req.id).update(status='rejected')

    elif action == 'reject':
        req.status = 'rejected'

    req.save()

    # Smart redirect
    if req.request_type == 'claim':
        return redirect('dogadoption_admin:claim_requests', post.id)
    else:
        return redirect('dogadoption_admin:adoption_requests', post.id)

# Authenticating users using face auth dashboard
@admin_required
def view_faceauth(request, user_id):
    user = get_object_or_404(User, id=user_id)

    # Get all face auth images for this user
    face_images = FaceImage.objects.filter(user=user)

    # Optionally include profile info
    profile = Profile.objects.filter(user=user).first()

    return render(request, 'admin_home/view_faceauth.html', {
        'user': user,
        'profile': profile,
        'face_images': face_images,
    })

#+++++++++++++++++++++ DOG CAPTURE REQUESTS  ++++++++++++++++++++++++++++=
@admin_required
@require_http_methods(["GET", "POST"])
def admin_dog_capture_requests(request):
    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'add_contact':
            name = (request.POST.get('contact_name') or '').strip()
            phone = (request.POST.get('contact_phone') or '').strip()
            if phone:
                DogCatcherContact.objects.create(
                    name=name,
                    phone_number=phone,
                    active=True
                )
                messages.success(request, "Dog catcher contact added.")
            else:
                messages.error(request, "Phone number is required.")

        elif action == 'toggle_contact':
            contact_id = request.POST.get('contact_id')
            contact = DogCatcherContact.objects.filter(id=contact_id).first()
            if contact:
                contact.active = not contact.active
                contact.save(update_fields=['active'])
                state = "activated" if contact.active else "deactivated"
                messages.success(request, f"Contact {state}.")

        elif action == 'delete_contact':
            contact_id = request.POST.get('contact_id')
            DogCatcherContact.objects.filter(id=contact_id).delete()
            messages.success(request, "Contact removed.")

        return redirect('dogadoption_admin:requests')

    requests = DogCaptureRequest.objects.select_related(
        'requested_by', 'assigned_admin'
    ).order_by('-created_at')

    map_points = []
    for req in requests:
        if req.latitude is not None and req.longitude is not None:
            scheduled_iso = req.scheduled_date.date().isoformat() if req.scheduled_date else ''
            scheduled_display = req.scheduled_date.strftime('%b %d, %Y %I:%M %p') if req.scheduled_date else ''
            map_points.append({
                'id': req.id,
                'user': req.requested_by.username,
                'reason': req.get_reason_display(),
                'status': req.get_status_display(),
                'status_key': req.status,
                'lat': float(req.latitude),
                'lng': float(req.longitude),
                'created_at': req.created_at.strftime('%b %d, %Y %I:%M %p'),
                'scheduled_date_iso': scheduled_iso,
                'scheduled_date_display': scheduled_display,
            })

    return render(request, 'admin_request/request.html', {
        'requests': requests,
        'map_points': map_points,
        'contacts': DogCatcherContact.objects.all(),
    })

@admin_required
def update_dog_capture_request(request, pk):
    req = get_object_or_404(DogCaptureRequest, pk=pk)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'accept':
            req.status = 'accepted'
            req.assigned_admin = request.user
            scheduled_raw = request.POST.get('scheduled_date')
            scheduled_dt = parse_datetime(scheduled_raw) if scheduled_raw else None
            if scheduled_dt and timezone.is_naive(scheduled_dt):
                scheduled_dt = timezone.make_aware(
                    scheduled_dt, timezone.get_current_timezone()
                )
            req.scheduled_date = scheduled_dt
            req.admin_message = request.POST.get('admin_message')

            if scheduled_dt:
                notify_at = scheduled_dt - timedelta(hours=8)
                req.notification_scheduled_for = notify_at
                req.notification_sent_at = None
            req.save()

            # Send immediately if the schedule is within the 8-hour window
            if scheduled_dt and notify_at <= timezone.now():
                contacts = list(
                    DogCatcherContact.objects.filter(active=True).values_list("phone_number", flat=True)
                )
                if contacts:
                    message = build_capture_message(req)
                    if send_sms(contacts, message):
                        req.notification_sent_at = timezone.now()
                        req.save(update_fields=['notification_sent_at'])

            messages.success(request, "Request accepted and scheduled.")

        elif action == 'decline':
            req.status = 'declined'
            req.admin_message = request.POST.get('admin_message')
            req.assigned_admin = request.user
            req.save()

            messages.warning(request, "Request declined.")

        return redirect('dogadoption_admin:requests')

    return render(request, 'admin_request/update_request.html', {
        'req': req
    })


#  ++++++++++++++++++++++  ANNOUNCEMENTS PAGE   ++++++++++++++++++++++++++++++++++++++
@admin_required
def announcement_list(request):

    announcements = DogAnnouncement.objects.all().prefetch_related('comments').order_by('-created_at')

    return render(request, 'admin_announcement/announcement.html', {
        'announcements': announcements
    })

#   -CREATING ANNOUNCEMENTS 
@admin_required
@require_http_methods(["GET", "POST"])
def announcement_create(request):

    if request.method == "POST":

        schedule_raw = request.POST.get("schedule_data")
        schedule = None

        if schedule_raw:
            try:
                schedule = json.loads(schedule_raw)
            except json.JSONDecodeError:
                schedule = None

        DogAnnouncement.objects.create(
            title=request.POST.get("title"),
            content=request.POST.get("content"),
            background_color=request.POST.get("background_color"),
            background_image=request.FILES.get("background_image"),
            schedule_data=schedule,
            created_by=request.user
        )

        return redirect("dogadoption_admin:admin_announcements")

    return render(request, "admin_announcement/create_announcement.html")


@admin_required
def announcement_comment(request, post_id):

    if request.method == "POST":
        AnnouncementComment.objects.create(
            announcement_id=post_id,
            user=request.user,
            comment=request.POST.get("comment")
        )

    return redirect("dogadoption_admin:admin_announcements")

@admin_required
def announcement_edit(request, post_id):
    post = DogAnnouncement.objects.get(id=post_id)

    if request.method == "POST":
        post.content = request.POST.get("content")
        post.post_type = request.POST.get("post_type", post.post_type)
        post.background_color = request.POST.get("background_color", post.background_color)
        if request.FILES.get("background_image"):
            post.background_image = request.FILES.get("background_image")
        post.save()
        return redirect("dogadoption_admin:admin_announcements")

    return render(request, "admin_announcement/edit_announcement.html", {
        "post": post
    })

@admin_required
def announcement_delete(request, post_id):
    post = get_object_or_404(DogAnnouncement, id=post_id)
    post.delete()

    return redirect("dogadoption_admin:admin_announcements")

@admin_required
def comment_reply(request, comment_id):
    comment = AnnouncementComment.objects.get(id=comment_id)

    if request.method == "POST":
        comment.reply = request.POST.get("reply")
        comment.save()
    return redirect("dogadoption_admin:admin_announcements")


#++++++++++++++++++++++++++++ USER MANAGEMENT PAGE +++++++++++++++++++++++++++++++++++++
@admin_required
def admin_users(request):
    query = request.GET.get('q', '')

    users = User.objects.select_related('profile').annotate(
        calculated_violations=Count(
            'postrequest',
            filter=Q(postrequest__request_type='claim')
        )
    )

    # Search functionality
    if query:
        users = users.filter(
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query)
        )

    users = users.order_by('-calculated_violations', 'first_name')

    return render(request, 'admin_user/users.html', {
        'users': users,
        'query': query
    })

def admin_user_search_results(request):
    query = request.GET.get('q', '')

    results = User.objects.select_related('profile').filter(
        Q(first_name__icontains=query) |
        Q(last_name__icontains=query) |
        Q(username__icontains=query)
    ).order_by('first_name')

    return render(request, 'admin_user/user_search_results.html', {
        'results': results,
        'query': query
    })


def admin_user_detail(request, id):
    user = get_object_or_404(User, id=id)
    return render(request, 'admin_user/user_detail.html', {'user': user})

def admin_user_search_results(request):
    """
    Separate template for search results
    """
    query = request.GET.get('q', '')

    results = User.objects.select_related('profile').filter(
        Q(first_name__icontains=query) |
        Q(last_name__icontains=query) |
        Q(username__icontains=query)
    ).order_by('first_name')

    context = {
        'results': results,
        'query': query,
    }

    return render(request, 'admin_user/user_search_results.html', context)


@admin_required
def admin_edit_profile(request):
    user = request.user
    profile, created = Profile.objects.get_or_create(
        user=user,
        defaults={
            "address": "",
            "age": 18,
            "consent_given": True
        }
    )

    if request.method == "POST":
        user.first_name = request.POST.get("first_name", "").strip()
        user.last_name = request.POST.get("last_name", "").strip()

        profile.middle_initial = request.POST.get("middle_initial", "").strip()
        profile.address = request.POST.get("address", "").strip()
        profile.age = request.POST.get("age") or profile.age

        if request.FILES.get("profile_image"):
            profile.profile_image = request.FILES["profile_image"]

        user.save()
        profile.save()
        messages.success(request, "Profile updated successfully.")
        return redirect("dogadoption_admin:admin_edit_profile")

    return render(request, "admin_profile/edit_profile.html", {
        "profile": profile
    })


@admin_required
def admin_notifications(request):
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "mark_all_read":
            AdminNotification.objects.filter(is_read=False).update(is_read=True)
        return redirect("dogadoption_admin:admin_notifications")

    notifications = AdminNotification.objects.all()
    return render(request, "admin_notifications/notifications.html", {
        "notifications": notifications,
    })


@admin_required
@require_POST
def mark_notification_read(request, pk):
    notif = get_object_or_404(AdminNotification, pk=pk)
    notif.is_read = True
    notif.save(update_fields=["is_read"])
    target = notif.url or "dogadoption_admin:admin_notifications"
    return redirect(target)

#+++++++++++++++++++++++++++++  ADMIN REGISTRATION  +++++++++++++++++++++++++++++++++++++++++


@admin_required
def register_dogs(request):
    # Admin-controlled barangay and date stored in session
    barangay = request.session.get('barangay', '')
    date = request.session.get('date', '')

    if request.method == 'POST':
        barangay = request.POST.get('barangay', barangay)
        date = request.POST.get('date', date)
        request.session['barangay'] = barangay
        request.session['date'] = date

        name = request.POST.get('name', '').strip()
        species = request.POST.get('species', 'Canine')
        sex = request.POST.get('sex', 'M')
        age = request.POST.get('age', '').strip()
        neutering = request.POST.get('neutering', 'No')
        color = request.POST.get('color', '').strip()
        owner_name = request.POST.get('owner_name', '').strip()

        if not name or not owner_name:
            messages.error(request, "Dog Name and Owner Name are required.")
            return redirect('dogadoption_admin:register_dogs')

        try:
            date_registered = datetime.strptime(date, '%Y-%m-%d').date()
        except ValueError:
            messages.error(request, "Invalid date format.")
            return redirect('dogadoption_admin:register_dogs')
        
        formatted_address = f"{barangay}, Bayawan City, Negros Oriental"

        dog = Dog(
            date_registered=date_registered,
            name=name,
            species=species,
            sex=sex,
            age=age,
            neutering_status=neutering,
            color=color,
            owner_name=owner_name,
            owner_address=formatted_address,
            barangay=barangay
        )
        dog.save()
        messages.success(request, f"Dog '{name}' registered successfully!")
        return redirect('dogadoption_admin:register_dogs')

    return render(request, 'admin_registration/registration.html', {
        'barangay': barangay,
        'date': date
    })




@admin_required
def registration_record(request):
    selected_barangay = request.GET.get('barangay', '').strip()

    barangay_list_parsed = [
        "Ali-is","Banaybanay","Banga","Boyco","Bugay","Cansumalig","Dawis","Kalamtukan",
        "Kalumboyan","Malabugas","Mandu-ao","Maninihon","Minaba","Nangka","Narra",
        "Pagatban","Poblacion","San Isidro","San Jose","San Miguel","San Roque","Suba",
        "Tabuan","Tayawan","Tinago","Ubos","Villareal","Villasol"
    ]

    if selected_barangay:
        dogs = Dog.objects.filter(
            barangay__iexact=selected_barangay
        ).order_by('-date_registered')
    else:
        dogs = Dog.objects.all().order_by('-date_registered')

    context = {
        'selected_barangay': selected_barangay,
        'dogs': dogs,
        'barangay_list_parsed': barangay_list_parsed,
    }

    return render(request, 'admin_registration/registration_record.html', context)

def download_registration(request, file_type):
    selected_barangay = request.GET.get('barangay', None)

    dogs = Dog.objects.all()

    if selected_barangay:
        dogs = dogs.filter(barangay__iexact=selected_barangay)

    # ================= EXCEL =================
    if file_type == 'excel':
        wb = Workbook()
        ws = wb.active
        ws.title = "Dog Registrations"

        headers = [
            'No.', 'Date', 'Dog Name', 'Species', 'Sex',
            'Age', 'Neutering', 'Owner Name', 'Owner Address'
        ]
        ws.append(headers)

        for idx, dog in enumerate(dogs, start=1):
            ws.append([
                idx,
                dog.date_registered.strftime("%m-%d-%Y") if dog.date_registered else "",
                dog.name,
                dog.species,
                dog.sex,
                dog.age,
                dog.neutering_status,
                dog.owner_name,
                dog.owner_address
            ])

        response = HttpResponse(
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )

        filename = f"Dog_Registrations_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        response['Content-Disposition'] = f'attachment; filename={filename}'

        wb.save(response)
        return response

    # ================= PDF =================
    elif file_type == 'pdf':
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)

        data = [[
            'No.', 'Date', 'Dog Name', 'Species', 'Sex',
            'Age', 'Neutering', 'Owner Name', 'Owner Address'
        ]]

        for idx, dog in enumerate(dogs, start=1):
            data.append([
                idx,
                dog.date_registered.strftime("%m-%d-%Y") if dog.date_registered else "",
                dog.name,
                dog.species,
                dog.sex,
                dog.age,
                dog.neutering_status,
                dog.owner_name,
                dog.owner_address
            ])

        table = Table(data)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.grey),
            ('TEXTCOLOR',(0,0),(-1,0),colors.whitesmoke),
            ('ALIGN',(0,0),(-1,-1),'CENTER'),
            ('FONTNAME', (0,0),(-1,0), 'Helvetica-Bold'),
            ('BOTTOMPADDING',(0,0),(-1,0),12),
            ('GRID', (0,0), (-1,-1), 1, colors.black),
        ]))

        doc.build([table])
        buffer.seek(0)

        response = HttpResponse(buffer, content_type='application/pdf')
        filename = f"Dog_Registrations_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        response['Content-Disposition'] = f'attachment; filename={filename}'

        return response

    return HttpResponse("Invalid file type.", status=400)
#certification for dogs views.py


@admin_required
def med_record(request, registration_id):
    registration = DogRegistration.objects.get(id=registration_id)

    vaccinations = VaccinationRecord.objects.filter(
        registration=registration
    ).order_by('-date')

    dewormings = DewormingTreatmentRecord.objects.filter(
        registration=registration
    ).order_by('-date')

    if request.method == "POST":
        record_type = request.POST.get("record_type")

        if record_type == "vaccination":
            VaccinationRecord.objects.create(
                registration=registration,
                date=request.POST.get("vac_date"),
                vaccine_name=request.POST.get("vaccine_name"),
                vaccine_expiry_date=request.POST.get("vaccine_expiry_date"),
                vaccination_expiry_date=request.POST.get("vaccination_expiry_date"),
                veterinarian=request.POST.get("vac_veterinarian"),
            )

        elif record_type == "deworming":
            DewormingTreatmentRecord.objects.create(
                registration=registration,
                date=request.POST.get("dew_date"),
                medicine_given=request.POST.get("medicine_given"),
                route=request.POST.get("route"),
                frequency=request.POST.get("frequency"),
                veterinarian=request.POST.get("dew_veterinarian"),
            )

        elif record_type == "all":
            VaccinationRecord.objects.create(
                registration=registration,
                date=request.POST.get("vac_date"),
                vaccine_name=request.POST.get("vaccine_name"),
                vaccine_expiry_date=request.POST.get("vaccine_expiry_date"),
                vaccination_expiry_date=request.POST.get("vaccination_expiry_date"),
                veterinarian=request.POST.get("vac_veterinarian"),
            )

            DewormingTreatmentRecord.objects.create(
                registration=registration,
                date=request.POST.get("dew_date"),
                medicine_given=request.POST.get("medicine_given"),
                route=request.POST.get("route"),
                frequency=request.POST.get("frequency"),
                veterinarian=request.POST.get("dew_veterinarian"),
            )

        return redirect('dogadoption_admin:med_records', registration_id=registration.id)

    context = {
        "registration": registration,
        "vaccinations": vaccinations,
        "dewormings": dewormings,
    }

    return render(request, "admin_registration/med_record.html", context)

@admin_required
def dog_certificate(request):
    settings = CertificateSettings.objects.first()

    if request.method == "POST":
        reg_no = request.POST.get("reg_no")

        if settings:
            if settings.reg_no != reg_no:
                settings.reg_no = reg_no
                settings.save()
        else:
            settings = CertificateSettings.objects.create(reg_no=reg_no)

        registration = DogRegistration.objects.create(
            reg_no=settings.reg_no,
            name_of_pet=request.POST.get('name_of_pet'),
            breed=request.POST.get('breed'),
            dob=request.POST.get('dob'),
            color_markings=request.POST.get('color_markings'),
            sex=request.POST.get('sex'),
            status=request.POST.get('status'),
            owner_name=request.POST.get('owner_name'),
            address=request.POST.get('address'),
            contact_no=request.POST.get('contact_no'),
        )

        #  Redirect to medical record with dog ID
        return redirect('dogadoption_admin:med_records', registration_id=registration.id)

    return render(request, 'admin_registration/dog_certificate.html', {'settings': settings})

@admin_required
def certificate_print(request, pk):
    registration = get_object_or_404(DogRegistration, pk=pk)

    vaccinations = VaccinationRecord.objects.filter(
        registration=registration
    ).order_by('-date')

    dewormings = DewormingTreatmentRecord.objects.filter(
        registration=registration
    ).order_by('-date')

    context = {
        'data': registration,
        'vaccinations': vaccinations,
        'dewormings': dewormings,
    }

    return render(request, 'admin_registration/certificate_print.html', context)

@admin_required
def certificate_list(request):
    certificates = DogRegistration.objects.all().order_by('-date_registered')
    return render(request, 'admin_registration/certificate_list.html', {
        'certificates': certificates
    })


@admin_required
def export_certificates_pdf(request):
    certificates = DogRegistration.objects.all().order_by('-date_registered')

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="certificates.pdf"'

    doc = SimpleDocTemplate(response)
    data = [["Reg No", "Pet Name", "Owner", "Date Issued"]]

    for cert in certificates:
        data.append([
            cert.reg_no,
            cert.name_of_pet,
            cert.owner_name,
            cert.date_registered.strftime("%b %d, %Y")
        ])

    table = Table(data)
    doc.build([table])
    return response

@admin_required
def export_certificates_word(request):
    certificates = DogRegistration.objects.all().order_by('-date_registered')

    document = Document()
    document.add_heading('Vaccination Certificates', level=1)

    table = document.add_table(rows=1, cols=4)
    headers = ["Reg No", "Pet Name", "Owner", "Date Issued"]

    for i, header in enumerate(headers):
        table.rows[0].cells[i].text = header

    for cert in certificates:
        row_cells = table.add_row().cells
        row_cells[0].text = cert.reg_no
        row_cells[1].text = cert.name_of_pet
        row_cells[2].text = cert.owner_name
        row_cells[3].text = cert.date_registered.strftime("%b %d, %Y")

    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
    response['Content-Disposition'] = 'attachment; filename="certificates.docx"'
    document.save(response)
    return response

@admin_required
def export_certificates_excel(request):
    certificates = DogRegistration.objects.all().order_by('-date_registered')

    wb = Workbook()
    ws = wb.active
    ws.title = "Certificates"

    ws.append(["Reg No", "Pet Name", "Owner", "Date Issued"])

    for cert in certificates:
        ws.append([
            cert.reg_no,
            cert.name_of_pet,
            cert.owner_name,
            cert.date_registered.strftime("%b %d, %Y")
        ])

    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = 'attachment; filename="certificates.xlsx"'
    wb.save(response)
    return response


#handles all the download/multi select


@admin_required
def export_selected_certificates(request):
    if request.method == "POST":
        selected_ids = request.POST.getlist('selected_ids')
        file_format = request.POST.get('format')

        registrations = DogRegistration.objects.filter(
            id__in=selected_ids
        ).order_by('-date_registered')

        # ================= PDF =================
        if file_format == "pdf":

            response = HttpResponse(content_type='application/pdf')
            response['Content-Disposition'] = 'attachment; filename="selected_certificates.pdf"'

            html_content = ""

            for reg in registrations:
                vaccinations = VaccinationRecord.objects.filter(registration=reg)
                dewormings = DewormingTreatmentRecord.objects.filter(registration=reg)

                rendered = render_to_string(
                    "admin_registration/certificate_pdf.html",
                    {
                        "data": reg,
                        "vaccinations": vaccinations,
                        "dewormings": dewormings,
                        "request": request
                    }
                )

                html_content += rendered
                html_content += '<div style="page-break-after: always;"></div>'

            pisa.CreatePDF(html_content, dest=response)
            return response

        # ================= WORD =================
        elif file_format == "word":
            ...
        
        # ================= EXCEL =================
        elif file_format == "excel":
            ...

    return HttpResponse("Invalid request", status=400)

@admin_required
def bulk_certificate_print(request):
    if request.method == "POST":
        selected_ids = request.POST.getlist("selected_ids")

        # ONLY fetch the selected certificates
        registrations = DogRegistration.objects.filter(id__in=selected_ids).order_by('id')

        certificates = []

        for registration in registrations:
            vaccinations = VaccinationRecord.objects.filter(
                registration=registration
            ).order_by('-date')

            dewormings = DewormingTreatmentRecord.objects.filter(
                registration=registration
            ).order_by('-date')

            certificates.append({
                "data": registration,
                "vaccinations": vaccinations,
                "dewormings": dewormings,
            })

        return render(
            request,
            "admin_registration/bulk_certificate_print.html",
            {"certificates": certificates}
        )

    return redirect("dogadoption_admin:certificate_list")


# Penalty and Citation  form
def citation_create(request):
    form = CitationForm(request.POST or None)
    latest_citation = Citation.objects.order_by('-id').first()
    citations_qs = Citation.objects.select_related('owner', 'penalty') \
        .prefetch_related('penalties', 'penalties__section') \
        .order_by('-id')[:10]
    citation_rows = []
    for citation in citations_qs:
        penalties = list(citation.penalties.all())
        if not penalties and citation.penalty_id:
            penalties = [citation.penalty]
        violations = ", ".join([p.title for p in penalties]) if penalties else "-"
        total_fees = sum([p.amount for p in penalties]) if penalties else 0
        citation_rows.append({
            "citation": citation,
            "violations": violations,
            "total_fees": total_fees,
        })
    penalties = Penalty.objects.filter(active=True).select_related('section').order_by('section__number', 'number')

    if request.method == 'POST' and form.is_valid():
        selected_ids = request.POST.getlist('penalties')
        selected_penalties = list(Penalty.objects.filter(id__in=selected_ids, active=True).order_by('section__number', 'number'))

        if not selected_penalties:
            messages.error(request, 'Please select at least one violation.')
        else:
            citation = form.save(commit=False)
            # Keep backward compatibility with existing single-penalty references.
            citation.penalty = selected_penalties[0]
            citation.save()
            citation.penalties.set(selected_penalties)
            return redirect('dogadoption_admin:citation_print', citation.pk)

    return render(request, 'admin_registration/citation_form.html', {
        'form': form,
        'latest_citation': latest_citation,
        'citation_rows': citation_rows,
        'penalties': penalties,
        'selected_penalty_ids': [int(x) for x in request.POST.getlist('penalties') if str(x).isdigit()] if request.method == 'POST' else [],
    })

def citation_print(request, pk):
    citation = get_object_or_404(Citation, pk=pk)
    penalties = Penalty.objects.filter(active=True).select_related('section').order_by('section__number', 'number')
    selected_penalties = list(citation.penalties.all().select_related('section').order_by('section__number', 'number'))
    if not selected_penalties and citation.penalty_id:
        selected_penalties = [citation.penalty]
    owner_address = "-"
    if citation.owner_id:
        try:
            owner_address = citation.owner.profile.address or "-"
        except Exception:
            owner_address = "-"

    return render(request, 'admin_registration/citation_print.html', {
        'citation': citation,
        'penalties': penalties,
        'selected_penalties': selected_penalties,
        'selected_penalty_ids': {p.id for p in selected_penalties},
        'owner_address': owner_address,
    })




def penalty_manager(request):
    sections = PenaltySection.objects.prefetch_related('penalties')

    # ALWAYS initialize forms
    s_form = SectionForm()
    p_form = PenaltyForm()

    if request.method == 'POST':

        if 'add_section' in request.POST:
            s_form = SectionForm(request.POST)
            if s_form.is_valid():
                s_form.save()
                s_form = SectionForm()   # reset form

        elif 'add_penalty' in request.POST:
            p_form = PenaltyForm(request.POST)
            if p_form.is_valid():
                p_form.save()
                p_form = PenaltyForm()   # reset form

    return render(request, 'admin_registration/penalty_manage.html', {
        'sections': sections,
        's_form': s_form,
        'p_form': p_form
    })
