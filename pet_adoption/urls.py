"""
URL configuration for pet_adoption project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path, register_converter
from django.conf import settings
from django.conf.urls.static import static
from .import views
from dogadoption_admin import views as admin_views
from .path_converters import (
    AdoptionRequestIDConverter,
    AdminPostIDConverter,
    AnnouncementIDConverter,
    CitationIDConverter,
    DogCaptureRequestIDConverter,
    MissingDogPostIDConverter,
    NotificationIDConverter,
    RegistrationIDConverter,
    UserAdoptionPostIDConverter,
    UserIDConverter,
)

register_converter(UserIDConverter, "userid")
register_converter(AdminPostIDConverter, "adminpostid")
register_converter(AdoptionRequestIDConverter, "adoptionreqid")
register_converter(UserAdoptionPostIDConverter, "useradoptpostid")
register_converter(MissingDogPostIDConverter, "missingpostid")
register_converter(DogCaptureRequestIDConverter, "captureid")
register_converter(AnnouncementIDConverter, "announcementid")
register_converter(RegistrationIDConverter, "registrationid")
register_converter(CitationIDConverter, "citationid")
register_converter(NotificationIDConverter, "notificationid")

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.root_redirect, name='root'),
    path('user/', include('user.urls')),
    path('vetadmin/analytics/dashboard/', admin_views.analytics_dashboard, name='analytics_dashboard_direct'),
    path('vetadmin/', include('dogadoption_admin.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

