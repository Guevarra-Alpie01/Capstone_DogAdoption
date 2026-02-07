from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.utils import timezone

from .models import Post, PostImage
from .forms import PostForm
from user.models import DogCaptureRequest, AdoptionRequest



# ADMIN-ONLY DECORATOR

def admin_required(view_func):
    @login_required(login_url='dogadoption_admin:admin_login')
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_staff:
            messages.error(request, "You do not have permission to access this page.")
            return redirect('dogadoption_admin:admin_login')
        return view_func(request, *args, **kwargs)
    return _wrapped_view



# AUTH VIEWS

def admin_login(request):
    """Custom admin login view"""
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(request, username=username, password=password)

        if user is not None:
            if user.is_staff:
                login(request, user)
                return redirect('dogadoption_admin:post_list')
            else:
                messages.error(request, 'You do not have admin access.')
        else:
            messages.error(request, 'Invalid username or password.')

    return render(request, 'admin_login.html')


@login_required
def admin_logout(request):
    logout(request)
    return redirect('dogadoption_admin:admin_login')



# ADMIN DASHBOARD
@admin_required
def admin_dashboard(request):
    return render(request, 'admin_base.html')


# POST / HOME PAGE

@admin_required
def create_post(request):
    if request.method == 'POST':
        post_form = PostForm(request.POST)

        if post_form.is_valid():
            post = post_form.save(commit=False)
            post.user = request.user
            post.save()

            # MULTIPLE IMAGE HANDLING (unchanged)
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

#Request
@admin_required
def update_request(request, req_id, action):
    req = get_object_or_404(AdoptionRequest, id=req_id)

    if action == 'accept':
        req.status = 'accepted'
    elif action == 'decline':
        req.status = 'declined'

    req.save()
    return redirect('dogadoption_admin:adoption_requests', req.post.id)


#adoption
@admin_required
def adoption_requests(request, post_id):
    post = get_object_or_404(Post, id=post_id)
    requests = post.adoption_requests.select_related('user')
    return render(request, 'admin_adoption/adoption_request.html', {
        'post': post,
        'requests': requests
    })
