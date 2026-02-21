from django.shortcuts import render, redirect , get_object_or_404
from django.contrib import messages
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.utils import timezone

from django.db.models import Q
import os
import json
import base64
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.core.files.base import ContentFile
from django.conf import settings

#MODELS.PY 
from dogadoption_admin.models import DogAnnouncement, AnnouncementReaction, AnnouncementComment
from .models import Profile, DogCaptureRequest, AdoptionRequest, FaceImage, OwnerClaim, ClaimImage
from dogadoption_admin.models import Post, PostRequest
from django.contrib.auth.models import User
from .models import UserAdoptionPost, UserAdoptionImage, UserAdoptionRequest, MissingDogPost
from .forms import UserAdoptionPostForm,MissingDogPostForm
 
# Decorator to allow only users
from collections import Counter


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
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        user = authenticate(request, username=username, password=password)

        if user is not None:
            # Prevent admins from logging in here
            if user.is_staff:
                return render(request, "login.html", {
                    "error": "Please login through the admin portal."
                })

            # Force logout any existing admin session before logging in as a user
            if request.user.is_authenticated and request.user.is_staff:
                logout(request)

            login(request, user)
            return redirect("user:user_home")

        return render(request, "login.html", {
            "error": "Invalid username or password"
        })

    return render(request, "login.html")



# Sign up for users
def signup_view(request):
    if request.method == "POST":
        username = request.POST.get("username")

        if User.objects.filter(username=username).exists():
            return render(request, "signup.html", {
                "error": "Username already exists"
            })

        # SAVE DATA TEMPORARILY (SESSION)
        request.session["signup_data"] = {
            "username": username,
            "password": request.POST.get("password"),
            "first_name": request.POST.get("first_name"),
            "last_name": request.POST.get("last_name"),
            "middle_initial": request.POST.get("middle_initial"),
            "address": request.POST.get("address"),
            "age": request.POST.get("age"),
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
        middle_initial=data["middle_initial"],
        address=data["address"],
        age=data["age"],
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

    query = request.GET.get('q')

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

    # ADMIN POSTS
    for p in admin_posts:
        days = hours = minutes = 0
        is_open_for_adoption = False

        if hasattr(p, 'is_open_for_adoption') and p.is_open_for_adoption():
            is_open_for_adoption = True
            diff = p.time_left()
            total_seconds = max(int(diff.total_seconds()), 0)

            days = total_seconds // 86400
            remainder = total_seconds % 86400
            hours = remainder // 3600
            remainder = remainder % 3600
            minutes = remainder // 60

        combined_posts.append({
            'post': p,
            'post_type': 'admin',
            'days_left': days,
            'hours_left': hours,
            'minutes_left': minutes,
            'is_open_for_adoption': is_open_for_adoption
        })

    # USER ADOPTION POSTS
    for p in user_posts:
        combined_posts.append({
            'post': p,
            'post_type': 'user',
            'days_left': 0,
            'hours_left': 0,
            'minutes_left': 0,
            'is_open_for_adoption': False
        })

    # MISSING POSTS
    for p in missing_posts:
        combined_posts.append({
            'post': p,
            'post_type': 'missing',
            'days_left': 0,
            'hours_left': 0,
            'minutes_left': 0,
            'is_open_for_adoption': False
        })

    # SORT ALL POSTS
    combined_posts = sorted(
        combined_posts,
        key=lambda x: x['post'].created_at,
        reverse=True
    )

    return render(request, 'home/user_home.html', {
        'posts': combined_posts,
        'query': query,
    })

@user_only
def create_user_adoption_post(request):
    if request.method == 'POST':
        form = UserAdoptionPostForm(request.POST, request.FILES)
        if form.is_valid():
            post = form.save(commit=False)
            post.owner = request.user
            post.save()

            # Save main image
            main_image = request.FILES.get('main_image')
            if main_image:
                UserAdoptionImage.objects.create(post=post, image=main_image)

            # Save extra images
            for img in request.FILES.getlist('extra_images'):
                UserAdoptionImage.objects.create(post=post, image=img)

            return redirect('user:user_home')
    else:
        form = UserAdoptionPostForm()

    return render(request, 'post_adopt.html', {'form': form})


@user_only
def adopt_user_post(request, post_id):
    post = get_object_or_404(UserAdoptionPost, id=post_id)

    if post.owner == request.user:
        return redirect('user:user_home')

    UserAdoptionRequest.objects.get_or_create(
        post=post,
        requester=request.user
    )

    return redirect('user:user_home')


from .models import MissingDogPost
from .forms import MissingDogPostForm


@user_only
def create_missing_post(request):
    if request.method == 'POST':
        form = MissingDogPostForm(request.POST, request.FILES)
        if form.is_valid():
            post = form.save(commit=False)
            post.owner = request.user
            post.save()
            messages.success(request, "Missing dog post created successfully 🐶")
            return redirect('user:user_home')
    else:
        form = MissingDogPostForm()

    return render(request, 'home/post_missing.html', {
        'form': form
    })

# VIEW FOR FACEBOOK SHARED LINK PREVIEW
@user_only
def post_detail(request, post_id):
    post = get_object_or_404(Post, id=post_id)
    return render(request, 'home/post_detail.html', {'post': post})


#USER REQUEST PAGE 
@user_only
def request_dog_capture(request):
    if request.method == 'POST':
        DogCaptureRequest.objects.create(
            requested_by=request.user,
            reason=request.POST.get('reason'),
            description=request.POST.get('description'),
            latitude=request.POST.get('latitude') or None,
            longitude=request.POST.get('longitude') or None,
            barangay=request.POST.get('barangay'),
            city=request.POST.get('city'),
            image=request.FILES.get('image')
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

    posts = Post.objects.all().prefetch_related("images").order_by("-created_at")

    # Filtering logic based on YOUR model
    if filter_type == "ready_claim":
        posts = [
            p for p in posts
            if p.status == "rescued" and p.is_open_for_adoption()
        ]

    elif filter_type == "ready_adopt":
        posts = [
            p for p in posts
            if p.status == "under_care" and p.is_open_for_adoption()
        ]

    elif filter_type == "adopted":
        posts = posts.filter(status="adopted")

    elif filter_type == "claimed":
        posts = posts.filter(status="reunited")

    elif filter_type == "all":
        posts = posts

    return render(request, "adopt/adopt_list.html", {
        "posts": posts,
        "current_filter": filter_type
    })

@user_only
def adopt_status(request):
    requests = AdoptionRequest.objects.filter(user=request.user).select_related('post')
    return render(request, 'adopt/adopt.html', {'requests': requests})

@user_only
def adopt_confirm(request, post_id):
    post = get_object_or_404(Post, id=post_id)

    # Block if already claimed or adopted
    if post.status in ['reunited', 'adopted']:
        messages.warning(request, "This dog is no longer available.")
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
        req = PostRequest.objects.create(
            user=request.user,
            post=post,
            request_type='adopt',
            status='pending'
        )

        for img in request.FILES.getlist('images'):
            ClaimImage.objects.create(claim=req, image=img)

        messages.success(
            request,
            "Adoption request submitted successfully! 🐾"
        )
        return redirect('user:user_home')

    return render(request, 'adopt/adopt_confirm.html', {'post': post})



@user_only
def announcement_list(request):
    posts = DogAnnouncement.objects.all().order_by('-created_at')

    # Add reaction counts for admin view
    for post in posts:
        reactions = post.reactions.values_list('reaction', flat=True)
        post.reaction_summary = Counter(reactions)  # e.g. {'LIKE': 3, 'LOVE': 1}

        # Optional: add user reaction if needed for non-admin
        if not request.user.is_staff:
            reaction = post.reactions.filter(user=request.user).first()
            post.user_reaction = reaction.get_reaction_display() if reaction else None

    return render(request, 'announcement/announcement.html', {
        'announcements': posts
    })

# POST endpoint to handle reactions
@user_only
@require_POST
def announcement_react(request, post_id):
    post = get_object_or_404(DogAnnouncement, id=post_id)
    reaction_type = request.POST.get('reaction')

    # Ensure it's a valid reaction
    if reaction_type not in dict(AnnouncementReaction.REACTION_CHOICES):
        return JsonResponse({'error': 'Invalid reaction'}, status=400)

    # Update or create reaction
    reaction, created = AnnouncementReaction.objects.update_or_create(
        announcement=post,
        user=request.user,
        defaults={'reaction': reaction_type}
    )

    # Return JSON with updated info
    total_count = post.reactions.count()
    user_reaction = reaction.get_reaction_display()

    return JsonResponse({
        'total': total_count,
        'user_reaction': user_reaction
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

    # 🚫 Block if already claimed or adopted
    if post.status in ['reunited', 'adopted']:
        messages.warning(request, "This dog is no longer available.")
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
        req = PostRequest.objects.create(
            user=request.user,
            post=post,
            request_type='claim',
            status='pending'
        )

        for img in request.FILES.getlist('images'):
            ClaimImage.objects.create(claim=req, image=img)

        messages.success(
            request,
            "Claim submitted successfully! Admin will review it carefully 🐾"
        )
        return redirect('user:user_home')

    return render(request, 'claim/claim_confirm.html', {'post': post})
