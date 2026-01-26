from django.shortcuts import render,redirect, get_object_or_404
from django.conf import settings
from django.contrib import messages
from dogadoption_admin .models import Post
# Create your views here.




def sidebar(request):
    return render (request, 'sidebar.html')

def base(request):
    return render (request, 'base.html')

def login_view(request):
    return render (request, 'login.html')

def signup_view(request):
    return render (request, 'signup.html')

def navigation(request):
    return render (request, 'firstnavigation.html')

#navigation links / home views
def user_home(request):
    return render (request, 'nav_links/user_home.html')

def post_feed(request):
    posts = Post.objects.all().order_by('-created_at')
    return render(request, 'nav_links/post_feed.html', {
        'posts': posts
    })
#navigation links / request views
def user_request(request):
    return render (request, 'nav_links/request.html')


#navigation links / claim views
def claim(request):
    return render (request, 'nav_links/claim.html')

#navigation links/ adopt views
def adopt(request):
    return render (request, 'nav_links/adopt.html')

#navigation links / announcement views
def announcement(request):
    return render (request, 'nav_links/announcement.html')


