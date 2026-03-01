from django.shortcuts import render, redirect , get_object_or_404
from django.contrib import messages
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.contrib.auth.models import User
from django.db.models import Q
import os
import json
import base64
from django.http import JsonResponse
from django.core.files.base import ContentFile
from django.conf import settings
from datetime import timedelta
from django.core.paginator import Paginator
from django.utils.dateparse import parse_date

#MODELS FROM ADMIN APP 
from dogadoption_admin.models import DogAnnouncement, AnnouncementComment
from dogadoption_admin.models import Post, PostRequest, GlobalAppointmentDate
from dogadoption_admin.models import Barangay

#MODELS FROM USER APP
from .models import Profile, DogCaptureRequest, AdoptionRequest, FaceImage, OwnerClaim, ClaimImage
from .models import UserAdoptionPost, UserAdoptionImage, UserAdoptionRequest, MissingDogPost

#FORMS.PY 
from .forms import UserAdoptionPostForm,MissingDogPostForm
# Decorator to allow only users


# USER-ONLY DECORATOR
def user_only(view_func):
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('user:login')
        if request.user.is_staff:
            return redirect('dogadoption_admin:post_list')  # admin goes to admin dashboard
        return view_func(request, *args, **kwargs)
    return wrapper

# User Authentication through log in 
def login_view(request):
    if request.user.is_authenticated:
        if request.user.is_staff:
            return redirect("dogadoption_admin:post_list")
        return redirect("user:user_home")

    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        user = authenticate(request, username=username, password=password)

        if user is not None:
            if user.is_staff:
                login(request, user)
                response = redirect("dogadoption_admin:post_list")
                response.set_cookie("admin_sessionid", request.session.session_key)
                return response

            login(request, user)
            response = redirect("user:user_home")
            response.delete_cookie("admin_sessionid")
            return response

        return render(request, "login.html", {
            "error": "Invalid username or password"
        })

    return render(request, "login.html")


def logout_view(request):
    logout(request)
    response = redirect("user:login")
    response.delete_cookie("admin_sessionid")
    return response



# Sign up for users
def _clean_barangay(value):
    return " ".join((value or "").split()).strip()


def _normalize_barangay(value):
    return "".join(ch.lower() for ch in _clean_barangay(value) if ch.isalnum())


def _resolve_barangay_name(value):
    normalized = _normalize_barangay(value)
    if not normalized:
        return ""
    for name in Barangay.objects.filter(is_active=True).values_list("name", flat=True):
        if _normalize_barangay(name) == normalized:
            return name
    return ""


def barangay_list_api(request):
    barangays = list(Barangay.objects.filter(is_active=True).values_list("name", flat=True))
    return JsonResponse({"barangays": barangays})


def signup_view(request):
    if request.method == "POST":
        username = (request.POST.get("username") or "").strip()
        password = request.POST.get("password") or ""
        confirm_password = request.POST.get("confirm_password") or ""
        first_name = (request.POST.get("first_name") or "").strip()
        last_name = (request.POST.get("last_name") or "").strip()
        raw_barangay = request.POST.get("address")
        barangay = _resolve_barangay_name(request.POST.get("address"))
        signup_form_data = {
            "username": username,
            "first_name": first_name,
            "last_name": last_name,
            "address": _clean_barangay(raw_barangay),
        }

        if not username:
            return render(request, "signup.html", {
                "error": "Username is required.",
                "signup_form_data": signup_form_data,
            })

        if User.objects.filter(username__iexact=username).exists():
            return render(request, "signup.html", {
                "error": "Username already exists",
                "signup_form_data": signup_form_data,
            })

        if password != confirm_password:
            return render(request, "signup.html", {
                "error": "Passwords do not match.",
                "signup_form_data": signup_form_data,
            })

        try:
            temp_user = User(username=username, first_name=request.POST.get("first_name"), last_name=request.POST.get("last_name"))
            validate_password(password, user=temp_user)
        except ValidationError as exc:
            return render(request, "signup.html", {
                "error": " ".join(exc.messages),
                "signup_form_data": signup_form_data,
            })

        if not barangay:
            return render(request, "signup.html", {
                "error": "Please select a valid barangay from the suggestions.",
                "signup_form_data": signup_form_data,
            })

        # SAVE DATA TEMPORARILY (SESSION)
        request.session["signup_data"] = {
            "username": username,
            "password": password,
            "first_name": first_name,
            "last_name": last_name,
            "middle_initial": "",
            "address": barangay,
            "age": 18,
        }

        # GO TO FACE AUTH STEP
        return redirect("user:face_auth")

    return render(request, "signup.html")

#editing users profileS
@user_only
def edit_profile(request):
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
        # User fields
        user.first_name = request.POST.get("first_name", "").strip()
        user.last_name = request.POST.get("last_name", "").strip()

        # Profile fields
        profile.middle_initial = request.POST.get("middle_initial", "").strip()
        profile.address = request.POST.get("address", "").strip()
        profile.age = request.POST.get("age") or profile.age
        profile.phone_number = request.POST.get("phone_number", "").strip()
        profile.facebook_url = request.POST.get("facebook_url", "").strip()

        if request.FILES.get("profile_image"):
            profile.profile_image = request.FILES["profile_image"]

        user.save()
        profile.save()

        messages.success(request, "Profile updated successfully")
        return redirect("user:edit_profile")

    return render(request, "edit_profile.html", {
        "profile": profile
    })


@csrf_exempt
def face_auth(request):
    if "signup_data" not in request.session:
        return redirect("user:signup")
    return render(request, "face_auth.html")

#Save Face Images

@csrf_exempt
def save_face(request):
    if request.method != "POST":
        return JsonResponse({"status": "error"}, status=400)

    if "signup_data" not in request.session:
        return JsonResponse({"status": "error", "message": "Signup step missing"}, status=400)

    data = json.loads(request.body.decode("utf-8"))
    images = data.get("images", [])

    if not images or len(images) < 3:
        return JsonResponse({"status": "error", "message": "At least 3 images required"}, status=400)

    temp_dir = os.path.join(settings.MEDIA_ROOT, "temp_faces")
    os.makedirs(temp_dir, exist_ok=True)
    saved_files = []

    for idx, img_data in enumerate(images):
        if ";base64," not in img_data:
            continue
        format, imgstr = img_data.split(";base64,")
        filename = f"{request.session['signup_data']['username']}_{idx}.png"
        filepath = os.path.join(temp_dir, filename)
        with open(filepath, "wb") as f:
            f.write(base64.b64decode(imgstr))
        saved_files.append(f"temp_faces/{filename}")

    request.session["face_images_files"] = saved_files
    return JsonResponse({"status": "ok"})



# Signup Complete
def signup_complete(request):
    if "signup_data" not in request.session or "face_images_files" not in request.session:
        return redirect("user:signup")

    data = request.session["signup_data"]
    images_files = request.session["face_images_files"]

    # Create user
    user = User.objects.create_user(
        username=data["username"],
        password=data["password"],
        first_name=data["first_name"],
        last_name=data["last_name"]
    )

    # Create profile
    profile = Profile.objects.create(
        user=user,
        middle_initial=data.get("middle_initial", ""),
        address=data.get("address", ""),
        age=data.get("age", 18),
        consent_given=True
    )

    # Move temp images into FaceImage model
    for path in images_files:
        full_path = os.path.join(settings.MEDIA_ROOT, path)
        with open(full_path, "rb") as f:
            FaceImage.objects.create(
                user=user,
                image=ContentFile(f.read(), name=os.path.basename(path))
            )
        # Remove temp file
        os.remove(full_path)

    # Clear session
    request.session.pop("signup_data", None)
    request.session.pop("face_images_files", None)

    return redirect("user:login")

# USER HOME VIEW
def user_home(request):
    # Redirect staff to admin dashboard
    if request.user.is_authenticated and request.user.is_staff:
        return redirect('dogadoption_admin:post_list')

    query = (request.GET.get('q') or '').strip()
    page_number = request.GET.get('page', 1)
    posts_per_page = 12

    # Admin posts
    admin_posts = Post.objects.all().prefetch_related('images').order_by('-created_at')

    # User adoption posts
    user_posts = UserAdoptionPost.objects.filter(status='available').prefetch_related('images')

    # Missing dog posts
    missing_posts = MissingDogPost.objects.filter(status='missing').order_by('-created_at')

    # SEARCH FILTER
    if query:
        admin_posts = admin_posts.filter(
            Q(caption__icontains=query) |
            Q(location__icontains=query) |
            Q(status__icontains=query)
        )

        user_posts = user_posts.filter(
            Q(dog_name__icontains=query) |
            Q(description__icontains=query) |
            Q(location__icontains=query)
        )

        missing_posts = missing_posts.filter(
            Q(dog_name__icontains=query) |
            Q(description__icontains=query) |
            Q(location__icontains=query)
        )

    combined_posts = []

    def format_posted_label(dt):
        if not dt:
            return ""
        now = timezone.now()
        delta = now - dt
        if delta < timedelta(minutes=1):
            return "Just now"
        if delta < timedelta(hours=1):
            minutes = max(int(delta.total_seconds() // 60), 1)
            return f"{minutes}m"
        if delta < timedelta(days=1):
            hours = max(int(delta.total_seconds() // 3600), 1)
            return f"{hours}h"
        if delta < timedelta(days=7):
            days = max(int(delta.total_seconds() // 86400), 1)
            return f"{days}d"
        return dt.strftime("%b %d, %Y")

    # ADMIN POSTS
    for p in admin_posts:
        days = hours = minutes = 0
        phase = p.current_phase() if hasattr(p, "current_phase") else "closed"
        is_open_for_adoption = phase in ["claim", "adopt"]

        if is_open_for_adoption:
            diff = p.time_left()
            total_seconds = max(int(diff.total_seconds()), 0)

            days = total_seconds // 86400
            remainder = total_seconds % 86400
            hours = remainder // 3600
            remainder = remainder % 3600
            minutes = remainder // 60

        deadline = None
        if phase == 'claim':
            deadline = p.claim_deadline()
        elif phase == 'adopt':
            deadline = p.adoption_deadline()

        combined_posts.append({
            'post': p,
            'post_type': 'admin',
            'days_left': days,
            'hours_left': hours,
            'minutes_left': minutes,
            'is_open_for_adoption': is_open_for_adoption,
            'phase': phase,
            'posted_label': format_posted_label(p.created_at),
            'deadline_iso': deadline.isoformat() if deadline else "",
        })

    # USER ADOPTION POSTS
    for p in user_posts:
        combined_posts.append({
            'post': p,
            'post_type': 'user',
            'days_left': 0,
            'hours_left': 0,
            'minutes_left': 0,
            'is_open_for_adoption': False,
            'phase': 'closed',
            'posted_label': format_posted_label(p.created_at),
        })

    # MISSING POSTS
    for p in missing_posts:
        combined_posts.append({
            'post': p,
            'post_type': 'missing',
            'days_left': 0,
            'hours_left': 0,
            'minutes_left': 0,
            'is_open_for_adoption': False,
            'phase': 'closed',
            'posted_label': format_posted_label(p.created_at),
        })

    # SORT ALL POSTS
    combined_posts = sorted(
        combined_posts,
        key=lambda x: x['post'].created_at,
        reverse=True
    )

    paginator = Paginator(combined_posts, posts_per_page)
    page_obj = paginator.get_page(page_number)

    return render(request, 'home/user_home.html', {
        'posts': page_obj.object_list,
        'page_obj': page_obj,
        'query': query,
    })

@user_only
def create_post(request):
    selected_type = request.GET.get("type", "adoption")
    if request.method == "POST":
        selected_type = request.POST.get("post_type", "adoption")

    adoption_form = UserAdoptionPostForm()
    missing_form = MissingDogPostForm()

    if request.method == "POST":
        if selected_type == "missing":
            missing_form = MissingDogPostForm(request.POST, request.FILES)
            if missing_form.is_valid():
                post = missing_form.save(commit=False)
                post.owner = request.user
                post.save()
                messages.success(request, "Missing dog post created successfully.")
                return redirect("user:user_home")
        else:
            adoption_form = UserAdoptionPostForm(request.POST, request.FILES)
            if adoption_form.is_valid():
                post = adoption_form.save(commit=False)
                post.owner = request.user
                post.save()

                main_image = request.FILES.get("main_image")
                if main_image:
                    UserAdoptionImage.objects.create(post=post, image=main_image)

                for img in request.FILES.getlist("extra_images"):
                    UserAdoptionImage.objects.create(post=post, image=img)

                messages.success(request, "Adoption post created successfully.")
                return redirect("user:user_home")

    return render(request, "home/post_create.html", {
        "selected_type": selected_type,
        "adoption_form": adoption_form,
        "missing_form": missing_form,
    })


@user_only
def adopt_user_post(request, post_id):
    post = get_object_or_404(UserAdoptionPost, id=post_id)

    if post.owner == request.user:
        return redirect('user:user_home')

    if post.status != "available":
        messages.warning(request, "This dog is no longer available.")
        return redirect("user:user_home")

    profile = Profile.objects.filter(user=request.user).first()
    if not profile or not profile.phone_number or not profile.facebook_url:
        messages.warning(request, "Please add your phone number and Facebook profile before requesting adoption.")
        return redirect("user:edit_profile")

    UserAdoptionRequest.objects.get_or_create(
        post=post,
        requester=request.user
    )

    return redirect('user:user_home')


@user_only
def user_adoption_requests(request):
    requests = UserAdoptionRequest.objects.filter(
        post__owner=request.user
    ).select_related("post", "requester", "requester__profile").order_by("-created_at")

    return render(request, "adopt/user_post_requests.html", {
        "requests": requests,
    })


@user_only
def user_adoption_request_action(request, req_id, action):
    req = get_object_or_404(
        UserAdoptionRequest,
        id=req_id,
        post__owner=request.user
    )

    if action == "accept":
        req.status = "approved"
        req.save(update_fields=["status"])
        UserAdoptionRequest.objects.filter(
            post=req.post
        ).exclude(id=req.id).update(status="rejected")
        req.post.status = "adopted"
        req.post.save(update_fields=["status"])
        messages.success(request, "Adoption request accepted.")
    elif action == "decline":
        req.status = "rejected"
        req.save(update_fields=["status"])
        messages.info(request, "Adoption request declined.")

    return redirect("user:user_adoption_requests")



# VIEW FOR FACEBOOK SHARED LINK PREVIEW
@user_only
def post_detail(request, post_id):
    post = get_object_or_404(Post, id=post_id)
    return render(request, 'home/post_detail.html', {'post': post})


#USER REQUEST PAGE 
@user_only
def request_dog_capture(request):
    if request.method == 'POST':
        image_file = request.FILES.get('image')
        captured_image = request.POST.get('captured_image')

        if not image_file and captured_image and ';base64,' in captured_image:
            _, imgstr = captured_image.split(';base64,', 1)
            filename = f"capture_{request.user.id}_{int(timezone.now().timestamp())}.png"
            image_file = ContentFile(base64.b64decode(imgstr), name=filename)

        new_req = DogCaptureRequest.objects.create(
            requested_by=request.user,
            reason=request.POST.get('reason'),
            description=request.POST.get('description'),
            latitude=request.POST.get('latitude') or None,
            longitude=request.POST.get('longitude') or None,
            barangay=request.POST.get('barangay'),
            city=request.POST.get('city'),
            image=image_file
        )
        from dogadoption_admin.models import AdminNotification
        AdminNotification.objects.create(
            title="New dog capture request",
            message=f"{request.user.username} submitted a request.",
            url="/vetadmin/dog-capture/requests/",
        )
        messages.success(request, "Request submitted successfully.")

    requests = DogCaptureRequest.objects.filter(
        requested_by=request.user
    ).order_by('-created_at')

    return render(request, 'user_request/request.html', {
        'requests': requests
    })




#CLAIM PAGE 
@user_only
def claim(request):
    return render(request, 'claim/claim.html')




#ADOPTION PAGE
@user_only
def adopt_list(request):
    filter_type = request.GET.get("filter", "all")

    posts_qs = Post.objects.all().prefetch_related("images").order_by("-created_at")
    posts = []

    # Filtering logic based on active timeline phase
    if filter_type == "ready_claim":
        posts = [
            p for p in posts_qs
            if p.is_open_for_claim()
        ]

    elif filter_type == "ready_adopt":
        posts = [
            p for p in posts_qs
            if p.is_open_for_adoption()
        ]

    elif filter_type == "adopted":
        posts = list(posts_qs.filter(status="adopted"))

    elif filter_type == "claimed":
        posts = list(posts_qs.filter(status="reunited"))

    elif filter_type == "all":
        posts = list(posts_qs)

    post_items = []
    for p in posts:
        phase = p.current_phase()
        days = hours = minutes = 0
        if phase in ["claim", "adopt"]:
            diff = p.time_left()
            total_seconds = max(int(diff.total_seconds()), 0)
            days = total_seconds // 86400
            remainder = total_seconds % 86400
            hours = remainder // 3600
            remainder = remainder % 3600
            minutes = remainder // 60
        post_items.append({
            "post": p,
            "phase": phase,
            "days_left": days,
            "hours_left": hours,
            "minutes_left": minutes,
        })

    return render(request, "adopt/adopt_list.html", {
        "posts": post_items,
        "current_filter": filter_type
    })

@user_only
def adopt_status(request):
    requests = PostRequest.objects.filter(
        user=request.user,
        request_type='adopt'
    ).select_related('post').order_by('-created_at')
    return render(request, 'adopt/adopt.html', {'requests': requests})

@user_only
def adopt_confirm(request, post_id):
    post = get_object_or_404(Post, id=post_id)
    available_dates = GlobalAppointmentDate.objects.filter(
        is_active=True,
        appointment_date__gte=timezone.localdate(),
    ).order_by('appointment_date')

    # Block if already claimed or adopted
    if post.status in ['reunited', 'adopted']:
        messages.warning(request, "This dog is no longer available.")
        return redirect('user:user_home')

    if not post.is_open_for_adoption():
        messages.warning(request, "Adoption is not open yet or has already closed.")
        return redirect('user:user_home')

    # Prevent duplicate adoption requests
    if PostRequest.objects.filter(
        user=request.user,
        post=post,
        request_type='adopt'
    ).exists():
        messages.info(request, "You already submitted an adoption request.")
        return redirect('user:user_home')

    if request.method == 'POST':
        appointment_date_raw = request.POST.get('appointment_date')
        appointment_date = parse_date(appointment_date_raw) if appointment_date_raw else None

        if not appointment_date:
            messages.error(request, "Please select an appointment date.")
            return render(request, 'adopt/adopt_confirm.html', {
                'post': post,
                'available_dates': available_dates,
            })

        if not available_dates.filter(appointment_date=appointment_date).exists():
            messages.error(request, "Selected appointment date is not available.")
            return render(request, 'adopt/adopt_confirm.html', {
                'post': post,
                'available_dates': available_dates,
            })

        req = PostRequest.objects.create(
            user=request.user,
            post=post,
            request_type='adopt',
            status='pending',
            appointment_date=appointment_date,
        )

        for img in request.FILES.getlist('images'):
            ClaimImage.objects.create(claim=req, image=img)

        messages.success(
            request,
            "Adoption request submitted successfully! ðŸ¾"
        )
        return redirect('user:user_home')

    return render(request, 'adopt/adopt_confirm.html', {
        'post': post,
        'available_dates': available_dates,
    })



@user_only
def announcement_list(request):
    posts = DogAnnouncement.objects.all() \
        .prefetch_related('comments') \
        .order_by('-created_at')

    return render(request, 'announcement/announcement.html', {
        'announcements': posts
    })


@user_only
def announcement_comment(request, post_id):
    if request.method == "POST":
        AnnouncementComment.objects.create(
            announcement_id=post_id,
            user=request.user,
            comment=request.POST.get("comment")
        )
    return redirect('user:announcement_list')

#CLAIM PAGE

@user_only
def my_claims(request):
    claims = PostRequest.objects.filter(
        user=request.user,
        request_type='claim'
    ).select_related('post').order_by('-created_at')

    return render(request, 'claim/claim.html', {
        'claims': claims
    })


@user_only
def claim_confirm(request, post_id):
    post = get_object_or_404(Post, id=post_id)
    available_dates = GlobalAppointmentDate.objects.filter(
        is_active=True,
        appointment_date__gte=timezone.localdate(),
    ).order_by('appointment_date')

    #  Block if already claimed or adopted
    if post.status in ['reunited', 'adopted']:
        messages.warning(request, "This dog is no longer available.")
        return redirect('user:user_home')

    if not post.is_open_for_claim():
        messages.warning(request, "Claim period has ended for this post.")
        return redirect('user:user_home')

    # Prevent duplicate claim requests
    if PostRequest.objects.filter(
        user=request.user,
        post=post,
        request_type='claim'
    ).exists():
        messages.info(request, "You already submitted a claim for this dog.")
        return redirect('user:user_home')

    if request.method == 'POST':
        appointment_date_raw = request.POST.get('appointment_date')
        appointment_date = parse_date(appointment_date_raw) if appointment_date_raw else None

        if not appointment_date:
            messages.error(request, "Please select an appointment date.")
            return render(request, 'claim/claim_confirm.html', {
                'post': post,
                'available_dates': available_dates,
            })

        if not available_dates.filter(appointment_date=appointment_date).exists():
            messages.error(request, "Selected appointment date is not available.")
            return render(request, 'claim/claim_confirm.html', {
                'post': post,
                'available_dates': available_dates,
            })

        req = PostRequest.objects.create(
            user=request.user,
            post=post,
            request_type='claim',
            status='pending',
            appointment_date=appointment_date,
        )

        for img in request.FILES.getlist('images'):
            ClaimImage.objects.create(claim=req, image=img)

        messages.success(
            request,
            "Claim submitted successfully! Admin will review it carefully ðŸ¾"
        )
        return redirect('user:user_home')

    return render(request, 'claim/claim_confirm.html', {
        'post': post,
        'available_dates': available_dates,
    })
