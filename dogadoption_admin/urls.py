from django.contrib import admin
from django.urls import path
from . import views

app_name="dogadoption_admin"

urlpatterns = [
    path('admin-/', admin.site.urls),
    path('login/', views.admin_login, name="admin_login"),
    path('dashboard/', views.admin_dashboard, name="admin_dashboard"),
    path('logout/', views.admin_logout, name="admin_logout"),
    path('admin_base/', views.admin_base, name="admin_base"),
    path('admin_sidebar/', views.admin_sidebar, name="admin_sidebar"),

    #urls for home 
    path('', views.post_list, name='post_list'),
    path('create/', views.create_post, name='create_post'),
]