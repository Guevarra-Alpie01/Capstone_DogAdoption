from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import user_passes_test
from django.views.decorators.http import require_POST
from django.db.models import Count, Q
from datetime import timedelta
from django.utils import timezone

from django.contrib import messages
from django.utils import timezone
from django.conf import settings
from django.http import JsonResponse
import json

#forms.py
from .forms import PostForm

#models
from .models import Post, PostImage , DogAnnouncement, AnnouncementComment, PostRequest
from user.models import DogCaptureRequest, AdoptionRequest,FaceImage, Profile,OwnerClaim, ClaimImage
from django.contrib.auth.models import User

# ADMIN-ONLY DECORATOR
def admin_required(view_func):
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_staff:
            return redirect('dogadoption_admin:admin_login')
        return view_func(request, *args, **kwargs)
    return wrapper

# AUTH VIEWS

def admin_login(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(request, username=username, password=password)

        if user is not None and user.is_staff:
            # Login normally
            login(request, user)

            # Save session key in a separate cookie for admin
            response = redirect('dogadoption_admin:post_list')
            response.set_cookie('admin_sessionid', request.session.session_key)
            return response

        messages.error(request, 'Invalid credentials or not an admin.')
        return render(request, 'admin_login.html')

    return render(request, 'admin_login.html')


@login_required
def admin_logout(request):
    logout(request)
    return redirect('dogadoption_admin:admin_login')


#  HOME PAGE OF THE ADMIN

from django.db.models import Count, Q

from .models import Post, PostImage, PostRequest
from .forms import PostForm
from user.models import Profile,FaceImage

# 🔹 CREATE POST
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


# 🔹 POST LIST WITH DROPDOWN FILTER
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

        if p.is_open_for_claim_adopt():
            diff = p.claim_deadline() - now
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
        })

    # Sort by newest
    enriched.sort(key=lambda x: x['post'].created_at, reverse=True)

    return render(request, 'admin_home/post_list.html', {
        'posts': enriched,
        'current_filter': status_filter,
    })

# 🔹 CLAIM REQUESTS
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


# 🔹 ADOPTION REQUESTS
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


# 🔹 ACCEPT / REJECT REQUEST
@admin_required
def update_request(request, req_id, action):
    req = get_object_or_404(PostRequest, id=req_id)
    post = req.post

    if action == 'accept':
        req.status = 'accepted'

        # 🔥 Move post automatically
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

    # 🔥 Smart redirect
    if req.request_type == 'claim':
        return redirect('dogadoption_admin:claim_requests', post.id)
    else:
        return redirect('dogadoption_admin:adoption_requests', post.id)

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

# DOG CAPTURE REQUESTS 
@admin_required
def admin_dog_capture_requests(request):
    requests = DogCaptureRequest.objects.select_related(
        'requested_by', 'assigned_admin'
    ).order_by('-created_at')

    return render(request, 'admin_request/request.html', {
        'requests': requests
    })

@admin_required
def update_dog_capture_request(request, pk):
    req = get_object_or_404(DogCaptureRequest, pk=pk)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'accept':
            req.status = 'accepted'
            req.assigned_admin = request.user
            req.scheduled_date = request.POST.get('scheduled_date')
            req.admin_message = request.POST.get('admin_message')
            req.save()

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


#ANNOUNCEMENTS PAGE
@admin_required
def announcement_list(request):

    announcements = DogAnnouncement.objects.all().prefetch_related('comments').order_by('-created_at')

    return render(request, 'admin_announcement/announcement.html', {
        'announcements': announcements
    })

#CREATING ANNOUNCEMENTS 
# views.py

from django.shortcuts import render, redirect
from django.views.decorators.http import require_http_methods
from functools import wraps
import json

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


#USER MANAGEMENT PAGE

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

#registration
from .models import Dog

from datetime import datetime
# views.py

import json
from datetime import datetime
from django.shortcuts import render, redirect
from django.contrib import messages
from .models import Dog

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

import datetime
import io
from django.http import HttpResponse
from openpyxl import Workbook
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4

from .models import Dog  # your Dog model

def download_registration(request, file_type):
    selected_barangay = request.GET.get('barangay', None)

    # Filter dogs
    dogs = Dog.objects.all()
    if selected_barangay:
        dogs = dogs.filter(owner_address__icontains=selected_barangay)

    # Create Excel
    if file_type == 'excel':
        wb = Workbook()
        ws = wb.active
        ws.title = "Dog Registrations"

        # Headers
        headers = ['No.', 'Date', 'Dog Name', 'Species', 'Sex', 'Age', 'Neutering', 'Owner Name', 'Owner Address']
        ws.append(headers)

        # Data
        for idx, dog in enumerate(dogs, start=1):
            ws.append([
                idx,
                dog.date_registered.strftime("%m-%d-%Y"),
                dog.name,
                dog.species,
                dog.sex,
                dog.age,
                dog.neutering_status,
                dog.owner_name,
                dog.owner_address
            ])

        # Save to response
        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        filename = f"Dog_Registrations_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        response['Content-Disposition'] = f'attachment; filename={filename}'
        wb.save(response)
        return response

    # Create PDF
    elif file_type == 'pdf':
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        data = [['No.', 'Date', 'Dog Name', 'Species', 'Sex', 'Age', 'Neutering', 'Owner Name', 'Owner Address']]
        for idx, dog in enumerate(dogs, start=1):
            data.append([
                idx,
                dog.date_registered.strftime("%m-%d-%Y"),
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
        filename = f"Dog_Registrations_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        response['Content-Disposition'] = f'attachment; filename={filename}'
        return response

    else:
        return HttpResponse("Invalid file type.", status=400)
    
@admin_required
def registration_record(request):
    selected_barangay = request.GET.get('barangay', '').strip()
    
    # Static list or dynamic list from DB
    barangay_list_parsed = [
        "Ali-is","Banaybanay","Banga","Boyco","Bugay","Cansumalig","Dawis","Kalamtukan",
        "Kalumboyan","Malabugas","Mandu-ao","Maninihon","Minaba","Nangka","Narra",
        "Pagatban","Poblacion","San Isidro","San Jose","San Miguel","San Roque","Suba",
        "Tabuan","Tayawan","Tinago","Ubos","Villareal","Villasol"
    ]

    if selected_barangay:
        dogs = Dog.objects.filter(barangay__iexact=selected_barangay).order_by('-date_registered')
    else:
        # Default view: show all dogs sorted by date
        dogs = Dog.objects.all().order_by('-date_registered')

    context = {
        'selected_barangay': selected_barangay,
        'dogs': dogs,
        'barangay_list_parsed': barangay_list_parsed,
    }
    return render(request, 'admin_registration/registration_record.html', context)

#certification for dogs views.py
from .models import DogRegistration, CertificateSettings
from .models import Pet, VaccinationRecord, DewormingTreatmentRecord

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
    return render(request, 'admin_registration/certificate_print.html', {'data': registration})

@admin_required
def certificate_list(request):
    certificates = DogRegistration.objects.all().order_by('-date_registered')
    return render(request, 'admin_registration/certificate_list.html', {'certificates': certificates})
