from django.contrib import admin
from django.urls import path
from . import views

app_name="dogadoption_admin"

urlpatterns = [
    path('admin-/',admin.site.urls)
]