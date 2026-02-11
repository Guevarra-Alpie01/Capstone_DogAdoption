from django.contrib import admin
from django.urls import path
from . import views
from .views import all_users_view

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
    path('announcements/<int:post_id>/react/', views.announcement_react, name='announcement_react'),
    path('announcements/<int:post_id>/comment/', views.announcement_comment, name='announcement_comment'),
    path('comments/<int:comment_id>/reply/', views.comment_reply, name='comment_reply'),

    #USER MANAGEMENT
    path("users/", all_users_view, name="users_list"),

    #REGISTRATION
    
    path('register/', views.register_dogs, name='register_dogs'),
    path('registration-record/', views.registration_record, name='registration_record'),

    #CERTIFICATION
    path('dog-certificate/', views.dog_certificate, name='dog_certificate'),
    path('certificate/<int:pk>/', views.certificate_print, name='certificate_print'),
    path('certificates/', views.certificate_list, name='certificate_list'),
]


