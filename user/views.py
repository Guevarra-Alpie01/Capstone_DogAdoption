from django.shortcuts import render, redirect , get_object_or_404
from django.contrib import messages
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.views.decorators.csrf import csrf_exempt
from dogadoption_admin.models import Post
from .models import Profile, DogCaptureRequest, AdoptionRequest, FaceImage, OwnerClaim, ClaimImage

from django.db.models import Q

# USER-ONLY DECORATOR
def user_only(view_func):
    @login_required(login_url='user:login')
    def _wrapped_view(request, *args, **kwargs):
        if request.user.is_staff:
            messages.error(request, "Admins cannot access user pages.")
            return redirect('dogadoption_admin:admin_login')
        return view_func(request, *args, **kwargs)
    return _wrapped_view


# User Authentication through log in 
def login_view(request):
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        user = authenticate(request, username=username, password=password)

        if user is not None:
            #  Prevent admins from logging in here
            if user.is_staff:
                return render(request, "login.html", {
                    "error": "Please login through the admin portal."
                })

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


import os
import json
import base64
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.core.files.base import ContentFile
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt

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


#Consent Page
def consent_view(request):
    if "signup_data" not in request.session or "face_images_files" not in request.session:
        return redirect("user:signup")

    if request.method == "POST":
        return redirect("user:signup_complete")

    return render(request, "consent.html")



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




# USER  HOME PAGE


def user_home(request):
    query = request.GET.get('q')

    posts = Post.objects.all().order_by('-created_at')

    if query:
        posts = posts.filter(
            Q(caption__icontains=query) |
            Q(location__icontains=query) |
            Q(status__icontains=query)
        )

    return render(request, 'home/user_home.html', {
        'posts': posts
    })



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

@login_required
@user_only
def adopt_status(request):
    requests = AdoptionRequest.objects.filter(user=request.user).select_related('post')
    return render(request, 'adopt/adopt.html', {'requests': requests})

@user_only
def adopt_confirm(request, post_id):
    post = get_object_or_404(Post, id=post_id)

    # Prevent duplicate requests
    if AdoptionRequest.objects.filter(user=request.user, post=post).exists():
        messages.info(request, "You already requested to adopt this dog 🐾")
        return redirect('user:adopt_status')

    if request.method == 'POST':
        AdoptionRequest.objects.create(
            user=request.user,
            post=post
        )
        messages.success(
            request,
            "Adoption request submitted! Please wait for admin verification 🐶"
        )
        return redirect('user:adopt_status')

    # GET request → show details + violations
    return render(request, 'adopt/adopt_confirm.html', {
        'post': post
    })


#ANNOUNCEMENT PAGE 
@user_only
def announcement(request):
    return render(request, 'announcement/announcement.html')



#CLAIM PAGE

@user_only
def my_claims(request):
    claims = OwnerClaim.objects.filter(
        user=request.user
    ).select_related('post').order_by('-submitted_at')

    return render(request, 'claim/claim.html', {
        'claims': claims
    })


@user_only
def claim_confirm(request, post_id):
    post = get_object_or_404(Post, id=post_id)

    if OwnerClaim.objects.filter(user=request.user, post=post).exists():
        messages.info(request, "You already submitted a claim for this dog.")
        return redirect('user:user_home')

    if request.method == 'POST':
        claim = OwnerClaim.objects.create(
            user=request.user,
            post=post,
            explanation=request.POST.get('explanation', ''),
            last_known_location=request.POST.get('last_known_location', ''),
        )

        for img in request.FILES.getlist('images'):
            ClaimImage.objects.create(claim=claim, image=img)

        messages.success(
            request,
            "Claim submitted successfully. Admin will review it carefully 🐾"
        )
        return redirect('user:user_home')

    return render(request, 'claim/claim_confirm.html', {
        'post': post
    })
