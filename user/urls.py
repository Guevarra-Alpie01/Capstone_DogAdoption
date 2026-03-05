from django.contrib import admin
from django.urls import path
from . import views

app_name="user"

urlpatterns = [
    path('admin/', admin.site.urls),
    path('user-login/', views.login_view, name="login"),
    path('logout/', views.logout_view, name='logout'),
    path('sign-up/', views.signup_view, name="signup"),
    path('barangays/', views.barangay_list_api, name="barangay_list_api"),
    path('signup/face-auth/', views.face_auth, name="face_auth"),
    path('signup/complete/', views.signup_complete, name="signup_complete"),
    path('signup/save-face/', views.save_face, name="save_face"),
    path("profile/edit/", views.edit_profile, name="edit_profile"),
    
    #navigation links/ home  urls
    path('',views.user_home, name="user_home"),
    path('post/create/', views.create_post, name='create_post'),
    path('user-adopt/<int:post_id>/', views.adopt_user_post, name='adopt_user_post'),
    path('user-adopt/requests/', views.user_adoption_requests, name='user_adoption_requests'),
    path('user-adopt/requests/<int:req_id>/<str:action>/', views.user_adoption_request_action, name='user_adoption_request_action'),

    #navigation links/ request  urls
    path('request/', views.request_dog_capture, name='dog_capture_request'),
    path('request/<int:req_id>/edit/', views.edit_dog_capture_request, name='edit_dog_capture_request'),
    path('request/<int:req_id>/delete/', views.delete_dog_capture_request, name='delete_dog_capture_request'),

    #navigation links/ claim  urls
    path('my-claims/', views.my_claims, name='my_claims'),
    path('claim/<int:post_id>/', views.claim_confirm, name='claim_confirm'),

    #navigation links/ adopt  urls
    path("adopt-list/", views.adopt_list, name="adopt_list"),
    path('adopt/<int:post_id>/', views.adopt_confirm, name='adopt_confirm'),
    path('adopt/status/', views.adopt_status, name='adopt_status'),


    #navigation links/ announcement  urls
    path('announcements/', views.announcement_list, name='announcement_list'),
    path('announcements/<int:post_id>/', views.announcement_detail, name='announcement_detail'),
    path('announcements/<int:post_id>/react/', views.announcement_react, name='announcement_react'),
    path('announcements/<int:post_id>/comment/', views.announcement_comment, name='announcement_comment'),
    path('announcements/share/<int:post_id>/', views.announcement_share_preview, name='announcement_share_preview'),

    #share button to facebook
    path('post/<int:post_id>/', views.post_detail, name='post_detail'),
    


  

]
