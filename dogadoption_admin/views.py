from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import user_passes_test
from django.views.decorators.http import require_POST

from django.contrib import messages
from django.utils import timezone
from django.conf import settings
from django.http import JsonResponse
import json

#forms.py
from .forms import PostForm

#models
from .models import Post, PostImage , DogAnnouncement, AnnouncementComment, AnnouncementReaction, PostRequest
from user.models import DogCaptureRequest, AdoptionRequest,FaceImage, Profile
from django.db.models import Count
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
@admin_required
def create_post(request):
    if request.method == 'POST':
        post_form = PostForm(request.POST)

        if post_form.is_valid():
            post = post_form.save(commit=False)
            post.user = request.user
            post.save()

            # MULTIPLE IMAGE HANDLING
            for image in request.FILES.getlist('images'):
                PostImage.objects.create(post=post, image=image)

            messages.success(request, "Post created successfully.")
            return redirect('dogadoption_admin:post_list')
    else:
        post_form = PostForm()

    return render(request, 'admin_home/create_post.html', {
        'post_form': post_form
    })

#LIST OF ALL THE POST OF DOG ADOPTION BY THE ADMIN 
@admin_required
def post_list(request):
    posts = Post.objects.all().prefetch_related('requests')

    for post in posts:
        post.pending_requests = post.requests.filter(status='pending').count()

    return render(request, 'admin_home/post_list.html', {
        'posts': posts
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

# REQUEST DOG ADOPTION 
@admin_required
def adoption_requests(request, post_id):
    post = get_object_or_404(Post, id=post_id)
    requests = post.requests.select_related('user')  # 

    return render(request, 'admin_adoption/adoption_request.html', {
        'post': post,
        'requests': requests
    })

@admin_required
def update_request(request, req_id, action):
    req = get_object_or_404(PostRequest, id=req_id)
    post = req.post

    if action == 'accept':
        req.status = 'accepted'

        # Update post status
        if req.request_type == 'claim':
            post.status = 'reunited'
        elif req.request_type == 'adopt':
            post.status = 'adopted'

        post.save()

        # Auto-reject other requests
        post.requests.exclude(id=req.id).update(status='rejected')

    elif action == 'reject':
        req.status = 'rejected'

    req.save()
    return redirect('dogadoption_admin:adoption_requests', post.id)


#ANNOUNCEMENTS PAGE
# Decorator to restrict access to admins
def admin_required(view_func):
    return user_passes_test(lambda u: u.is_staff, login_url='/admin/login/')(view_func)


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
@admin_required
def announcement_create(request):
    if request.method == "POST":
        DogAnnouncement.objects.create(
            content=request.POST.get("content"),
            post_type=request.POST.get("post_type", "COLOR"),
            background_color=request.POST.get("background_color", "#4f46e5"),
            background_image=request.FILES.get("background_image"),
            created_by=request.user
        )
        return redirect("dogadoption_admin:announcement_list")

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


#USES MANAGEMENT PAGE
@admin_required
def all_users_view(request):
    users = User.objects.filter(is_staff=False).prefetch_related(
        "faceimage_set", "profile"
    )

    return render(request, "admin_user/users.html", {
        "users": users
    })