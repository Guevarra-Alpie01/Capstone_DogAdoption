from django.shortcuts import render,redirect, get_object_or_404
from django.conf import settings
from django.contrib import messages


def admin_base(request):
    return render (request, 'admin_base.html')

def admin_sidebar(request):
    return render (request, 'admin_sidebar.html')
