from django.contrib import admin
from django.urls import path
from . import views

app_name="user"

urlpatterns = [
    # Shared admin passthrough and authentication routes
    path('admin/', admin.site.urls),
    path('user-login/', views.login_view, name="login"),
    path('google/login/', views.google_auth_login_view, name="google_auth_login"),
    path('privacy-policy/', views.privacy_policy, name="privacy_policy"),
    path('data-deletion/', views.data_deletion, name="data_deletion"),
    path('logout/', views.logout_view, name='logout'),
    path('notifications/open/', views.open_notification, name='open_notification'),
    path('notifications/summary/', views.notification_summary, name='notification_summary'),
    path('notifications/seen/', views.mark_notifications_seen, name='mark_notifications_seen'),
    path('sign-up/', views.signup_view, name="signup"),
    path('verify-email/<str:uidb64>/<str:token>/', views.verify_email, name="verify_email"),

    # Shared profile and utility routes
    path('barangays/', views.barangay_list_api, name="barangay_list_api"),
    path("profile/edit/", views.edit_profile, name="edit_profile"),
    path("profile/view/<userid:user_id>/", views.admin_view_user_profile, name="admin_view_user_profile"),
    path("profile/<userid:user_id>/", views.view_user_profile, name="view_user_profile"),
    path("profile/requester/<userid:user_id>/", views.view_requester_profile, name="view_requester_profile"),
    path("profile/posts/adoption/<useradoptpostid:post_id>/delete/", views.delete_user_adoption_post, name="delete_user_adoption_post"),
    path("profile/posts/missing/<missingpostid:post_id>/delete/", views.delete_missing_dog_post, name="delete_missing_dog_post"),

    # Navigation 1/5: Home
    path('', views.user_home, name="user_home"),
    path('search/', views.home_search, name='home_search'),
    path('post/create/', views.create_post, name='create_post'),
    path('user-adopt/requests/', views.user_adoption_requests, name='user_adoption_requests'),
    path('user-adopt/<useradoptpostid:post_id>/', views.adopt_user_post, name='adopt_user_post'),
    path('user-adopt/<useradoptpostid:post_id>/detail/', views.user_adoption_post_detail, name='user_adoption_post_detail'),
    path('user-adopt/requests/<adoptionreqid:req_id>/<str:action>/', views.user_adoption_request_action, name='user_adoption_request_action'),
    path('post/<adminpostid:post_id>/', views.post_detail, name='post_detail'),

    # Navigation 2/5: Request
    path('request/', views.request_dog_capture, name='dog_capture_request'),
    path('request/<captureid:req_id>/edit/', views.edit_dog_capture_request, name='edit_dog_capture_request'),
    path('request/<captureid:req_id>/delete/', views.delete_dog_capture_request, name='delete_dog_capture_request'),

    # Navigation 3/5: Claim
    path('claim-list/', views.claim_list, name='claim_list'),
    path('my-claims/', views.my_claims, name='my_claims'),
    path('claim/<adminpostid:post_id>/', views.claim_confirm, name='claim_confirm'),

    # Navigation 4/5: Announcement
    path('announcements/', views.announcement_list, name='announcement_list'),
    path('announcements/<announcementid:post_id>/', views.announcement_detail, name='announcement_detail'),
    path('announcements/<announcementid:post_id>/comment/', views.announcement_comment, name='announcement_comment'),
    path('announcements/share/<announcementid:post_id>/', views.announcement_share_preview, name='announcement_share_preview'),

    # Navigation 5/5: Adopt
    path("adopt-list/", views.adopt_list, name="adopt_list"),
    path('adopt/status/', views.adopt_status, name='adopt_status'),
    path('adopt/<adminpostid:post_id>/', views.adopt_confirm, name='adopt_confirm'),
]
