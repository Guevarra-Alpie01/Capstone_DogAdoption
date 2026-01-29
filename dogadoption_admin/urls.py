from django.contrib import admin
from django.urls import path
from . import views

app_name = "dogadoption_admin"

urlpatterns = [
    # Django admin (optional – usually stays in project urls.py)
    path('admin-/', admin.site.urls),

    # Auth
    path('admin-login/', views.admin_login, name="admin_login"),
    path('logout/', views.admin_logout, name="admin_logout"),

    # Admin dashboard
    path('dashboard/', views.admin_dashboard, name="admin_dashboard"),

    # Posts
    path('list/', views.post_list, name='post_list'),
    path('create/', views.create_post, name='create_post'),

    # Dog capture requests
    path('dog-capture-requests/', views.admin_dog_capture_requests, name='requests'),
]
