from django.shortcuts import render,redirect, get_object_or_404
from django.conf import settings
from django.contrib import messages
from dogadoption_admin .models import Post
from django.contrib.auth.models import User
from django.contrib.auth import login, logout, authenticate
from .models import Profile 


# this is for the navigations
def sidebar(request):
    return render (request, 'sidebar.html')

def base(request):
    return render (request, 'base.html')

def login_view(request):
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            return redirect("user:base")  # redirect after login
        else:
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

        # Prevent duplicate usernames
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

        login(request, user)  # auto-login after signup
        return redirect("user:user_home")

    return render(request, "signup.html")


def navigation(request):
    return render (request, 'firstnavigation.html')


#navigation links / home views
def user_home(request):
    posts = Post.objects.all().order_by('-created_at')
    return render(request, 'home/user_home.html', {
        'posts': posts
    })

    
#navigation links / request views
def user_request(request):
    return render (request, 'request/request.html')


#navigation links / claim views
def claim(request):
    return render (request, 'claim/claim.html')

#navigation links/ adopt views
def adopt(request):
    return render (request, 'adopt/adopt.html')

#navigation links / announcement views
def announcement(request):
    return render (request, 'announcement/announcement.html')


