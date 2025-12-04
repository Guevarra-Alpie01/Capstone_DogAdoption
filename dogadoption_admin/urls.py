from django.contrib import admin
from django.urls import path
from . import views

app_name="dogadoption_admin"

urlpatterns = [
    path('admin-/',admin.site.urls),
    path('admin_base/', views.admin_base, name="admin_base"),
    path('admin_sidebar/', views.admin_sidebar, name="admin_sidebar"),
]