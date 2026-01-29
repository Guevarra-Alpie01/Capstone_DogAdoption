from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User

from dogadoption_admin.models import Post
from .models import Profile, DogCaptureRequest


# =========================
# USER-ONLY DECORATOR
# =========================
def user_only(view_func):
    @login_required(login_url='user:login')
    def _wrapped_view(request, *args, **kwargs):
        if request.user.is_staff:
            messages.error(request, "Admins cannot access user pages.")
            return redirect('dogadoption_admin:admin_dashboard')
        return view_func(request, *args, **kwargs)
    return _wrapped_view


# =========================
# AUTH VIEWS (USER)
# =========================
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


def signup_view(request):
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        first_name = request.POST.get("first_name")
        last_name = request.POST.get("last_name")

        middle_initial = request.POST.get("middle_initial")
        address = request.POST.get("address")
        age = request.POST.get("age")

        if User.objects.filter(username=username).exists():
            return render(request, "signup.html", {
                "error": "Username already exists"
            })

        user = User.objects.create_user(
            username=username,
            password=password,
            first_name=first_name,
            last_name=last_name
        )

        Profile.objects.create(
            user=user,
            middle_initial=middle_initial,
            address=address,
            age=age
        )

        login(request, user)
        return redirect("user:user_home")

    return render(request, "signup.html")


# =========================
# USER PAGES
# =========================

def user_home(request):
    posts = Post.objects.all().order_by('-created_at')
    return render(request, 'home/user_home.html', {
        'posts': posts
    })


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
        return redirect('user:dog_capture_request')

    return render(request, 'request/request.html')


@user_only
def claim(request):
    return render(request, 'claim/claim.html')


@user_only
def adopt(request):
    return render(request, 'adopt/adopt.html')


@user_only
def announcement(request):
    return render(request, 'announcement/announcement.html')
