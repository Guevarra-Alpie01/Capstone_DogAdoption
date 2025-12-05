from django.shortcuts import render, redirect, get_object_or_404
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User


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
