from django.contrib import admin
from django.urls import path
from . import views

app_name = "dogadoption_admin"

urlpatterns = [
    # Django admin (optional – usually stays in project urls.py)
    path('admin-/', admin.site.urls),

    # Auth
    path('admin-login/', views.admin_login, name="admin_login"),
    path('logout/', views.admin_logout, name="admin_logout"),
    path('post-list/', views.post_list, name='post_list'),
    path('create/', views.create_post, name='create_post'),

    # Dog capture requests
    path('dog-capture/requests/',views.admin_dog_capture_requests,name='requests'),
    path('dog-capture/request/<int:pk>/update/',views.update_dog_capture_request,name='update_dog_capture_request'),


    # admin/urls.py
    path('post/<int:post_id>/requests/', views.adoption_requests, name='adoption_requests'),
    path('request/<int:req_id>/<str:action>/', views.update_request, name='update_request'),

    #announcement
    path('admin/announcements/', views.announcement_list, name='admin_announcements'),
    path("announcement/create/", views.announcement_create, name="announcement_create"),
    path("like/<int:post_id>/", views.announcement_like, name="announcement_like"),
    path("comment/<int:post_id>/", views.announcement_comment, name="announcement_comment"),


]
