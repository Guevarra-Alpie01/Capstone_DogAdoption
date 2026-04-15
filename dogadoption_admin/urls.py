from django.contrib import admin
from django.urls import path

from . import views

app_name = "dogadoption_admin"

urlpatterns = [
    # Shared admin and authentication routes
    path('admin-/', admin.site.urls),
    path('admin-login/', views.admin_login, name="admin_login"),
    path('logout/', views.admin_logout, name="admin_logout"),

    # Navigation 1/5: Home
    path('post-list/', views.post_list, name='post_list'),
    path('post-history/', views.post_history, name='post_history'),
    path('posts/<adminpostid:post_id>/history-record/', views.record_history_status, name='record_history_status'),
    path('create/', views.create_post, name='create_post'),
    path('posts/<adminpostid:post_id>/edit/', views.update_post, name='update_post'),
    path('posts/<adminpostid:post_id>/pin/', views.toggle_post_pin, name='toggle_post_pin'),
    path('posts/<adminpostid:post_id>/phase/', views.toggle_post_phase, name='toggle_post_phase'),
    path('posts/<adminpostid:post_id>/finalize/', views.finalize_post, name='finalize_post'),
    path('posts/<adminpostid:post_id>/delete/', views.delete_post, name='delete_post'),
    path('post/<adminpostid:post_id>/requests/', views.adoption_requests, name='adoption_requests'),
    path('request/<adoptionreqid:req_id>/<str:action>/', views.update_request, name='update_request'),
    path('posts/<adminpostid:post_id>/claims/', views.claim_requests, name='claim_requests'),
    path('user-post-requests/', views.user_post_requests, name='user_post_requests'),
    path('user-post-requests/<str:post_type>/<int:post_id>/<str:action>/', views.user_post_request_action, name='user_post_request_action'),

    # Navigation 2/5: Request
    path('dog-capture/requests/', views.admin_dog_capture_requests, name='requests'),
    path('dog-capture/request/<captureid:pk>/update/', views.update_dog_capture_request, name='update_dog_capture_request'),

    # Navigation 3/5: Register
    # Register link 1/5: Registration
    path('register/', views.register_dogs, name='register_dogs'),
    path('barangays/', views.barangay_list_api, name='barangay_list_api'),
    path('registration/users/search/', views.registration_user_search_api, name='registration_user_search_api'),

    # Register link 2/5: Registration List
    path('registration/profile/<userid:user_id>/', views.registration_owner_profile, name='registration_owner_profile'),
    path('registration-record/', views.registration_record, name='registration_record'),
    path('registration_record/download/<str:file_type>/', views.download_registration, name='download_registration'),

    # Register link 3/5: Vaccination
    path("med-records/<registrationid:registration_id>/", views.med_record, name="med_records"),
    path('dog-certificate/', views.dog_certificate, name='dog_certificate'),

    # Register link 4/5: Vaccination List
    path('certificate/<registrationid:pk>/', views.certificate_print, name='certificate_print'),
    path('certificates/', views.certificate_list, name='certificate_list'),
    path('export/pdf/', views.export_certificates_pdf, name='export_certificates_pdf'),
    path('export/word/', views.export_certificates_word, name='export_certificates_word'),
    path('export/excel/', views.export_certificates_excel, name='export_certificates_excel'),
    path("certificates/bulk-print/", views.bulk_certificate_print, name="bulk_certificate_print"),

    # Register link 5/5: Citation
    path('citation/lookup/', views.citation_print_lookup, name='citation_print_lookup'),
    path('citation/new/', views.citation_create, name='citation_create'),
    path('citation/<citationid:pk>/print/', views.citation_print, name='citation_print'),
    path('penalties/', views.penalty_manager, name='penalty_manage'),

    # Navigation 4/5: Announcement
    path('admin/announcements/', views.announcement_list, name='admin_announcements'),
    path('announcements/create/', views.announcement_create, name='announcement_create'),
    path(
        'announcements/create/<slug:category_slug>/',
        views.announcement_create_form,
        name='announcement_create_form'
    ),
    path('announcements/<announcementid:post_id>/edit/', views.announcement_edit, name='announcement_edit'),
    path('announcements/<announcementid:post_id>/bucket/', views.announcement_update_bucket, name='announcement_update_bucket'),
    path('announcements/<announcementid:post_id>/delete/', views.announcement_delete, name='announcement_delete'),

    # Navigation 5/5: Analytics
    path('analytics/dashboard/', views.analytics_dashboard, name='analytics_dashboard'),

    # Shared admin utilities
    path('users/', views.admin_users, name='admin_users'),
    path('admin/user/<userid:id>/', views.admin_user_detail, name='admin_user_detail'),
    path('users/search/', views.admin_user_search_results, name='admin_user_search'),
    path('users/<userid:id>/violations/', views.admin_user_violations, name='admin_user_violations'),
    path('users/<userid:id>/violations/letter/', views.admin_user_violation_letter, name='admin_user_violation_letter'),
    path('profile/edit/', views.admin_edit_profile, name='admin_edit_profile'),
    path('notifications/summary/', views.notification_summary, name='notification_summary'),
    path('notifications/', views.admin_notifications, name='admin_notifications'),
    path('notifications/<notificationid:pk>/read/', views.mark_notification_read, name='notification_read'),
]

