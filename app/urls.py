"""
URL configuration for app project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
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
from django.urls import path, include
from home import views as home_views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    # path("admin/", admin.site.urls),
    path("upload-licence/", home_views.uploadLicense, name="home.upload-license"),
    path("", home_views.customLogin, name="home.login"),
    path("add-company/", home_views.addCompany, name="home.add-company"),
    path("dashboard/", include("home.urls")),

    path("dashboard/license_history", home_views.license_history, name="home.license_history"), #will remove this in shared app
    path("dashboard/create-license", home_views.createLicenseAd, name="home.create_license"), #will remove this in shared app
    path("dashboard/download-license/<int:id>", home_views.downloadLicenseAd, name="home.download_license"), #will remove this in shared app
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
