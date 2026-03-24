from django.shortcuts import redirect, render
from dogadoption_admin.access import get_staff_landing_url

def root_redirect(request):
    if request.user.is_authenticated:
        if request.user.is_staff:
            return redirect(get_staff_landing_url(request.user))
        else:
            return redirect('user:user_home')
    return redirect('user:user_home')
