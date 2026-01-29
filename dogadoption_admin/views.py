from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User

from .models import Post, PostImage
from .forms import PostForm
from user.models import DogCaptureRequest


# =========================
# ADMIN-ONLY DECORATOR
# =========================
def admin_required(view_func):
    @login_required(login_url='dogadoption_admin:admin_login')
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_staff:
            messages.error(request, "You do not have permission to access this page.")
            return redirect('dogadoption_admin:admin_login')
        return view_func(request, *args, **kwargs)
    return _wrapped_view


# =========================
# AUTH VIEWS
# =========================
def admin_login(request):
    """Custom admin login view"""
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(request, username=username, password=password)

        if user is not None:
            if user.is_staff:
                login(request, user)
                return redirect('dogadoption_admin:admin_dashboard')
            else:
                messages.error(request, 'You do not have admin access.')
        else:
            messages.error(request, 'Invalid username or password.')

    return render(request, 'admin_login.html')


@login_required
def admin_logout(request):
    logout(request)
    return redirect('dogadoption_admin:admin_login')


# =========================
# ADMIN DASHBOARD
# =========================
@admin_required
def admin_dashboard(request):
    return render(request, 'admin_base.html')


# =========================
# POSTS (ADMIN)
# =========================
@admin_required
def create_post(request):
    if request.method == 'POST':
        post_form = PostForm(request.POST)

        if post_form.is_valid():
            post = post_form.save(commit=False)
            post.user = request.user
            post.save()

            # ✅ MULTIPLE FILE HANDLING (CORRECT WAY)
            for image in request.FILES.getlist('images'):
                PostImage.objects.create(post=post, image=image)

            messages.success(request, "Post created successfully.")
            return redirect('dogadoption_admin:post_list')

    else:
        post_form = PostForm()

    return render(request, 'admin_home/create_post.html', {
        'post_form': post_form
    })




@admin_required
def post_list(request):
    posts = Post.objects.all().order_by('-created_at')
    return render(request, 'admin_home/post_list.html', {'posts': posts})


# =========================
# DOG CAPTURE REQUESTS (ADMIN)
# =========================
@admin_required
def admin_dog_capture_requests(request):
    requests = DogCaptureRequest.objects.select_related(
        'requested_by', 'assigned_admin'
    ).order_by('-created_at')

    return render(request, 'admin_request/request.html', {
        'requests': requests
    })
