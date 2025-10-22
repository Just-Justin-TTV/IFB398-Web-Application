"""
ASGI config for app1 project.

This file contains the ASGI application used for deploying the Django project.
It exposes the ASGI callable as a module-level variable named ``application``.

For more information on ASGI deployment, see:
https://docs.djangoproject.com/en/5.1/howto/deployment/asgi/
"""

import os
from django.core.asgi import get_asgi_application

# Set the default Django settings module for the 'asgi' environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'app1.settings')

# Create an ASGI application instance to handle asynchronous requests
application = get_asgi_application()
