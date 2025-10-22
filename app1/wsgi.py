"""
WSGI config for app1 project.

This file contains the WSGI configuration required to serve the Django project
using a WSGI-compatible web server. It exposes the WSGI callable as a
module-level variable named `application`.

For more information on WSGI and deployment, see:
https://docs.djangoproject.com/en/5.1/howto/deployment/wsgi/
"""

import os  # Import os to set environment variables

from django.core.wsgi import get_wsgi_application  # Import the WSGI application function from Django

# Set the default Django settings module for the 'app1' project.
# This ensures the WSGI application uses the correct settings.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'app1.settings')

# Create the WSGI application object that the WSGI server can use to communicate with Django
application = get_wsgi_application()
