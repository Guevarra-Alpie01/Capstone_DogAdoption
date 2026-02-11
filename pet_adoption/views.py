from django.shortcuts import redirect, render

def root_redirect(request):
    if request.user.is_authenticated:
        if request.user.is_staff:
            return redirect('dogadoption_admin:post_list')
        else:
            return redirect('user:user_home')
    return redirect('user:user_home')