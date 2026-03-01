from django.contrib import admin
from django.urls import path
from . import views
from .views import admin_users

app_name = "dogadoption_admin"

urlpatterns = [
    # Django admin
    path('admin-/', admin.site.urls),

    # Auth
    path('admin-login/', views.admin_login, name="admin_login"),
    path('logout/', views.admin_logout, name="admin_logout"),

    #ADMIN HOME
    path('post-list/', views.post_list, name='post_list'),
    path('create/', views.create_post, name='create_post'),
    path('appointments/', views.appointment_calendar, name='appointment_calendar'),

    # DOG CAPTURE REQUESTS
    path('dog-capture/requests/',views.admin_dog_capture_requests,name='requests'),
    path('dog-capture/request/<int:pk>/update/',views.update_dog_capture_request,name='update_dog_capture_request'),
    path('user/<int:user_id>/faceauth/', views.view_faceauth, name='view_faceauth'),



    #ADOPTION REQUEST OF USERS 
    path('post/<int:post_id>/requests/', views.adoption_requests, name='adoption_requests'),
    path('request/<int:req_id>/<str:action>/', views.update_request, name='update_request'),
    path('posts/<int:post_id>/claims/', views.claim_requests, name='claim_requests'),
  
    #ADMIN ANNOUNCEMENTS
    path('admin/announcements/', views.announcement_list, name='admin_announcements'),
    path('announcements/create/', views.announcement_create, name='announcement_create'),
    path('announcements/<int:post_id>/edit/', views.announcement_edit, name='announcement_edit'),
    path('announcements/<int:post_id>/delete/', views.announcement_delete, name='announcement_delete'),
    path('announcements/<int:post_id>/comment/', views.announcement_comment, name='announcement_comment'),
    path('comments/<int:comment_id>/reply/', views.comment_reply, name='comment_reply'),

    #USER MANAGEMENT
    path('users/', views.admin_users, name='admin_users'),
    path('admin/user/<int:id>/', views.admin_user_detail, name='admin_user_detail'),
    path('users/search/', views.admin_user_search_results, name='admin_user_search'),
    path('profile/edit/', views.admin_edit_profile, name='admin_edit_profile'),
    path('notifications/', views.admin_notifications, name='admin_notifications'),
    path('notifications/<int:pk>/read/', views.mark_notification_read, name='notification_read'),

    #REGISTRATION
    
    path('register/', views.register_dogs, name='register_dogs'),
    path('barangays/', views.barangay_list_api, name='barangay_list_api'),
    path('registration-record/', views.registration_record, name='registration_record'),
     path('registration_record/download/<str:file_type>/', views.download_registration, name='download_registration'),
    path("med-records/<int:registration_id>/",views.med_record,name="med_records"),


    #CERTIFICATION
    path('dog-certificate/', views.dog_certificate, name='dog_certificate'),
    path('certificate/<int:pk>/', views.certificate_print, name='certificate_print'),
    path('certificates/', views.certificate_list, name='certificate_list'),
    path('export/pdf/', views.export_certificates_pdf, name='export_certificates_pdf'),
    path('export/word/', views.export_certificates_word, name='export_certificates_word'),
    path('export/excel/', views.export_certificates_excel, name='export_certificates_excel'),
    path('export_selected_certificates/', views.export_selected_certificates, name='export_selected_certificates'),
    path("certificates/bulk-print/",views.bulk_certificate_print,name="bulk_certificate_print"),

    #PENALTIES AND CITATIONS
    path('citation/new/', views.citation_create, name='citation_create'),
    path('citation/<int:pk>/print/', views.citation_print, name='citation_print'),

    # PENALTY MANAGEMENT (custom admin)
    path('penalties/', views.penalty_manager, name='penalty_manage'),
]


