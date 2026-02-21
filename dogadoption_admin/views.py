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
from .models import Post, PostImage , DogAnnouncement, AnnouncementComment, AnnouncementReaction, PostRequest
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
    # Fetch all announcements with related comments & reactions
    announcements = DogAnnouncement.objects.all().prefetch_related('comments', 'reactions')

    for post in announcements:
        # Build reaction summary
        reactions = post.reactions.values('reaction').annotate(count=Count('id'))
        summary = {r['reaction']: r['count'] for r in reactions}

        # Ensure all reaction types exist
        for key in ["LIKE", "LOVE", "WOW", "SAD", "ANGRY"]:
            summary.setdefault(key, 0)
        post.reaction_summary = summary

        # Current user's reaction (for logged-in users)
        if request.user.is_authenticated:
            user_reaction_obj = post.reactions.filter(user=request.user).first()
            post.user_reaction = user_reaction_obj.reaction if user_reaction_obj else None
        else:
            post.user_reaction = None

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
@require_http_methods(["GET", "POST"])   # ✅ ADDED: Restrict methods properly
def announcement_create(request):

    if request.method == "POST":

        # ✅ ADDED: Safe JSON parsing for schedule
        schedule_raw = request.POST.get("schedule_data")
        schedule = None

        if schedule_raw:
            try:
                schedule = json.loads(schedule_raw)
            except json.JSONDecodeError:
                schedule = None

        DogAnnouncement.objects.create(
            content=request.POST.get("content"),
            post_type=request.POST.get("post_type", "COLOR"),
            background_color=request.POST.get("background_color", "#4f46e5"),
            background_image=request.FILES.get("background_image"),
            schedule_data=schedule,   # ✅ ADDED
            created_by=request.user
        )

        return redirect("dogadoption_admin:admin_announcements")

    return render(request, "admin_announcement/create_announcement.html")



@admin_required
@require_POST
def announcement_react(request, post_id):
    reaction_type = request.POST.get("reaction")
    post = DogAnnouncement.objects.get(id=post_id)

    existing = post.reactions.filter(user=request.user).first()

    if existing and existing.reaction == reaction_type:
        # Remove reaction if same clicked again
        existing.delete()
        user_reaction = None
    else:
        obj, _ = post.reactions.update_or_create(
            user=request.user,
            announcement=post,
            defaults={"reaction": reaction_type}
        )
        user_reaction = obj.get_reaction_display()

    return JsonResponse({
        "total": post.reactions.count(),
        "user_reaction": user_reaction
    })


@admin_required
def announcement_comment(request, post_id):
    if request.method == "POST":
        AnnouncementComment.objects.create(
            announcement_id=post_id,
            user=request.user,
            comment=request.POST.get("comment")
        )
    return redirect("dogadoption_admin:announcement_list")

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

@login_required
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
        owner_address = request.POST.get('owner_address', '').strip()

        if not name or not owner_name:
            messages.error(request, "Dog Name and Owner Name are required.")
            return redirect('dogadoption_admin:register_dogs')

        try:
            date_registered = datetime.strptime(date, '%Y-%m-%d').date()
        except ValueError:
            messages.error(request, "Invalid date format.")
            return redirect('dogadoption_admin:register_dogs')

        dog = Dog(
            date_registered=date_registered,
            name=name,
            species=species,
            sex=sex,
            age=age,
            neutering_status=neutering,
            color=color,
            owner_name=owner_name,
            owner_address=owner_address,
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

    # Get unique barangays, sort alphabetically
    barangay_list = list(Dog.objects.values_list('barangay', flat=True).distinct().order_by('barangay'))
    barangay_list_json = json.dumps(barangay_list)  # Serialize to JSON string for JS usage

    if selected_barangay:
        # Case-insensitive partial match to show results even with partial typing
        dogs = Dog.objects.filter(barangay__icontains=selected_barangay).order_by('-date_registered')
    else:
        # Show recent 20 records if no barangay selected
        dogs = Dog.objects.all().order_by('-date_registered')[:20]

    context = {
        'selected_barangay': selected_barangay,
        'dogs': dogs,
        'barangay_list': barangay_list_json,  # Pass JSON string here
    }
    return render(request, 'admin_registration/registration_record.html', context)


#certification for dogs views.py
from .models import DogRegistration, CertificateSettings



from django.shortcuts import render, redirect
from .models import DogRegistration, CertificateSettings

@admin_required
def dog_certificate(request):
    settings = CertificateSettings.objects.first()  # get current reg no if exists

    if request.method == "POST":
        reg_no = request.POST.get("reg_no")

        # Update settings if reg_no changed manually
        if settings:
            if settings.reg_no != reg_no:
                settings.reg_no = reg_no
                settings.save()
        else:
            # First time creating settings
            settings = CertificateSettings.objects.create(reg_no=reg_no)

        # Create DogRegistration
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

        # Check print option
        if request.POST.get('print_immediately'):
            settings.print_immediately = True
        else:
            settings.print_immediately = False
        settings.save()

        # Redirect accordingly
        if settings.print_immediately:
            return redirect('dogadoption_admin:certificate_print', registration.id)
        else:
            return redirect('dogadoption_admin:certificate_list')

    return render(request, 'admin_registration/dog_certificate.html', {'settings': settings})


@admin_required
def certificate_print(request, pk):
    registration = get_object_or_404(DogRegistration, pk=pk)
    return render(request, 'admin_registration/certificate_print.html', {'data': registration})

@admin_required
def certificate_list(request):
    certificates = DogRegistration.objects.all().order_by('-date_registered')
    return render(request, 'admin_registration/certificate_list.html', {'certificates': certificates})
