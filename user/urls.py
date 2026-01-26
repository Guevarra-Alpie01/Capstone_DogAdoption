from django.contrib import admin
from django.urls import path
from . import views

app_name="user"

urlpatterns = [
    path('admin/', admin.site.urls),
    path('base/', views.base, name="base"),
    path('sidebar/',views.sidebar, name="sidebar"),
    path('login/', views.login_view, name="login"),
    path('sign-up/', views.signup_view, name="signup"),
    path('navigation/', views.navigation, name="firstnavigation"),

    #navigation links/ home  urls
    path('',views.user_home, name="user_home"),
    path('feed/', views.post_feed, name='post_feed'),

    #navigation links/ request  urls
    path('request/', views.user_request, name="request"),

    #navigation links/ claim  urls
    path('claim/', views.claim, name="claim"),

    #navigation links/ adopt  urls
    path('adopt/',views.adopt, name="adopt"),

    #navigation links/ announcement  urls
    path('announcement/', views.announcement, name="announcement"),


  

]