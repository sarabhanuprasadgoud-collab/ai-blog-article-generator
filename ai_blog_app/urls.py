"""
URL configuration for ai_blog_app project.

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
from django.conf import settings
from django.conf.urls.static import static

# Main URL configuration for the ai_blog_app project
# - Admin panel: /admin/
# - Blog generator app: includes blog_generator/urls.py
# - Media files (uploads): served in development only
urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('blog_generator.urls'))
    # Add namespace='blog_generator' → avoids future naming collisions.
    # Then you can reverse URLs like:
    # {% url 'blog_generator:generate-blog' %}
]

# Serve media files only during development (DEBUG=True)
if settings.DEBUG:
    urlpatterns += static( settings.MEDIA_URL, document_root=settings.MEDIA_ROOT )