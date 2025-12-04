from django.contrib import admin
from django.urls import path
from . import views

app_name="navigation"

urlpatterns = [
    path('admin/', admin.site.urls),
    path('base/', views.base, name="base"),
    path('',views.user_home, name="user_home"),
    path('sidebar/',views.sidebar, name="sidebar"),

    

]