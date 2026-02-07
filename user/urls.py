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
    path('signup/face-auth/', views.face_auth, name="face_auth"),
    path('signup/consent/', views.consent_view, name="consent"),
    path('signup/complete/', views.signup_complete, name="signup_complete"),
    path('signup/save-face/', views.save_face, name="save_face"),
    #navigation links/ home  urls
    path('',views.user_home, name="user_home"),

    #navigation links/ request  urls
    path('request/', views.request_dog_capture, name='dog_capture_request'),

    #navigation links/ claim  urls
    path('my-claims/', views.my_claims, name='my_claims'),
    path('claim/<int:post_id>/', views.claim_confirm, name='claim_confirm'),

    #navigation links/ adopt  urls
    path('adopt/<int:post_id>/', views.adopt_confirm, name='adopt_confirm'),
    path('adopt/status/', views.adopt_status, name='adopt_status'),



    #navigation links/ announcement  urls
    path('announcement/', views.announcement, name="announcement"),


  

]