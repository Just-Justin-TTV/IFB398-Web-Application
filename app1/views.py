import os
import pandas as pd
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.shortcuts import render, redirect
from django.db import connection
import hashlib
import sqlite3
from django.shortcuts import render
from .models import ClassTargets, Interventions
from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from django.contrib.auth import login
from django.contrib import messages
from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from .models import ClassTargets
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect
from django.contrib.auth import logout

# Step 1: Home page with "Get Started" button
def create_project_step2(request):
    return render(request, 'create_project_2.html')

def create_project(request):
    sidebar_items = [
        {'url': 'dashboard', 'icon': 'dashboard', 'label': 'Dashboard'},
        {'url': 'projects', 'icon': 'folder', 'label': 'Projects'},
        {'url': '#', 'icon': 'build', 'label': 'Interventions'},
        {'url': '#', 'icon': 'calculate', 'label': 'Cost Matrix'},
        {'url': '#', 'icon': 'description', 'label': 'Reports'},
        {'url': '#', 'icon': 'settings', 'label': 'Settings'},
    ]
    return render(request, 'create_project.html', {'sidebar_items': sidebar_items})


@login_required(login_url='login')
def home(request):
    return render(request, 'home.html')

def projects_view(request):
    return render(request, 'projects.html', {}, content_type='text/html')

def dashboard_view(request):
    return render(request, 'dashboard.html')


from django.http import HttpResponse


def register_view(request):
    return render(request, 'register.html')

def login_view(request):
    if request.method == 'POST':
        email = request.POST['email']
        password = request.POST['password1']
        confirm_password = request.POST['password2']
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, full_name FROM Users WHERE email=%s AND password_hash=%s",
                [email, password_hash]
            )
            user = cursor.fetchone()
        if user:
            # Store user in session
            request.session['user_email'] = email
            request.session['user_name'] = user[1]
            return redirect('dashboard')
        else:
            return render(request, 'login.html', {'error': 'Invalid credentials.'})
    return render(request, 'login.html')

def logout_view(request):
    if request.method == "POST":
        logout(request)
        messages.success(request, "You have successfully logged out.")
        return redirect('login')
    else:
        return redirect('home')


# Unused placeholder (can be removed if not needed)
def calculator_results(request):
    return render(request, 'calculator_results.html')

# Step 2: Calculator form and processing
def calculator(request):
    if request.method == 'GET':
        # Fetch all class targets for the form
        class_targets_qs = ClassTargets.objects.all().values('class_name', 'target_rating')
        class_targets = [
            {'class': ct['class_name'], 'target_rating': ct['target_rating']}
            for ct in class_targets_qs
        ]
        return render(request, 'calculator.html', {'class_targets': class_targets})

    elif request.method == 'POST':
        # Get total budget
        global_budget = float(request.POST.get('global_budget', 1e6))

        # Extract per-class targets
        targets = {
            key[6:]: float(value)
            for key, value in request.POST.items()
            if key.startswith('class_')
        }


        # Get all interventions grouped by class and sorted by impact
        interventions = (
            Interventions.objects
            .exclude(class_name__isnull=True)
            .exclude(name__isnull=True)
            .order_by('class_name')
        )

        # Organize into groups by class
        grouped_results = {}
        for row in interventions:
            cls = row.class_name
            if cls not in grouped_results:
                grouped_results[cls] = []
            grouped_results[cls].append(row)

        return render(
            request,
            'calculator_results.html',
            {
                'grouped_results': grouped_results,
                'global_budget': global_budget,
                'targets': targets  
            }
        )
