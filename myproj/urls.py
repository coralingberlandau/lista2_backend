"""
URL configuration for myproj project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
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
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('lista.urls'))
]

# Uploaded list images are served by Django itself, in every mode. (The static()
# helper only works with DEBUG=True, which would break images in production.)
# On a host that can map a URL straight to a folder, e.g. PythonAnywhere's "Static
# files" table, map /images/ to <project>/static/images for better performance;
# requests then never reach this route.
def serve_media(request, path):
    """Serve an uploaded image from MEDIA_ROOT."""
    return serve(request, path, document_root=settings.MEDIA_ROOT)


urlpatterns += [
    re_path(r'^' + settings.MEDIA_URL.lstrip('/') + r'(?P<path>.*)$', serve_media),
]

# Admin CSS/JS: served by Django only in debug mode. In production run
# `python manage.py collectstatic` and map /static/ to the staticfiles folder.
urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
