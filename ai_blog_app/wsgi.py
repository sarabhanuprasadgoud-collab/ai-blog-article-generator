"""
WSGI config for ai_blog_app project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

# This WSGI application is used for deploying with WSGI servers like Gunicorn or uWSGI.
# Example: gunicorn ai_blog_app.wsgi:application

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ai_blog_app.settings')

application = get_wsgi_application()
