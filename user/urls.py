from django.contrib import admin
from django.urls import path
from . import views
from django.contrib.auth import views as auth_views

app_name="user"

urlpatterns = [
    path('admin/', admin.site.urls),
    path('user-login/', views.login_view, name="login"),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('sign-up/', views.signup_view, name="signup"),

    #navigation links/ home  urls
    path('',views.user_home, name="user_home"),

    #navigation links/ request  urls
     path('request/', views.request_dog_capture, name='dog_capture_request'),

    #navigation links/ claim  urls
    path('claim/', views.claim, name="claim"),

    #navigation links/ adopt  urls
    path('adopt/',views.adopt, name="adopt"),

    #navigation links/ announcement  urls
    path('announcement/', views.announcement, name="announcement"),


  

]