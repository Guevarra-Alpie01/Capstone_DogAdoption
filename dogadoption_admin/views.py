from django.shortcuts import render, redirect, get_object_or_404
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from .models import Post, PostImage
from .forms import PostForm, ImageForm


def admin_login(request):
    """Custom admin login view"""
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        # Authenticate user
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            # Check if user is staff (admin)
            if user.is_staff:
                login(request, user)
                return redirect('dogadoption_admin:admin_dashboard')
            else:
                messages.error(request, 'You do not have admin access.')
        else:
            messages.error(request, 'Invalid username or password.')
    
    return render(request, 'admin_login.html')


@login_required(login_url='dogadoption_admin:admin_login')
def admin_dashboard(request):
    if not request.user.is_staff:
        return redirect('dogadoption_admin:admin_login')
    return render(request, 'admin_base.html')


def admin_logout(request):
    logout(request)
    return redirect('dogadoption_admin:admin_login')


def admin_base(request):
    return render(request, 'admin_base.html')


def admin_sidebar(request):
    return render(request, 'admin_sidebar.html')


#for user home views

@login_required
def create_post(request):
    if request.method == 'POST':
        post_form = PostForm(request.POST)
        image_form = ImageForm(request.POST, request.FILES)

        if post_form.is_valid() and image_form.is_valid():
            post = post_form.save(commit=False)
            post.user = request.user
            post.save()

            images = request.FILES.getlist('images')
            for image in images:
                PostImage.objects.create(post=post, image=image)

            return redirect('dogadoption_admin:post_list')

    else:
        post_form = PostForm()
        image_form = ImageForm()

    return render(request, 'create_post.html', {
        'post_form': post_form,
        'image_form': image_form
    })

def post_list(request):
    posts = Post.objects.all().order_by('-created_at')
    return render(request, 'post_list.html', {'posts': posts})
