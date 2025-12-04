from django.shortcuts import render,redirect, get_object_or_404
from django.conf import settings
from django.contrib import messages
# Create your views here.


def user_home(request):
    return render (request, 'user_home.html')

def sidebar(request):
    return render (request, 'sidebar.html')

def base(request):
    return render (request, 'base.html')


