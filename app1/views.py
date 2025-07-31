import os
import pandas as pd
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.shortcuts import render, redirect
from django.db import connection
import hashlib
import sqlite3

# Step 1: Home page with "Get Started" button
def create_project_step2(request):
    return render(request, 'create_project_2.html')

def create_project(request):
    return render(request, 'create_project.html')

def home(request):
    return render(request, 'home.html')

def projects_view(request):
    return render(request, 'projects.html', {}, content_type='text/html')

def dashboard_view(request):
    return render(request, 'dashboard.html')


from django.http import HttpResponse

def register_view(request):
    if request.method == "POST":
        email = request.POST.get("email")
        password = request.POST.get("password1")
        confirm_password = request.POST.get("password2")

        full_name = request.POST.get("full_name")

        password_hash = hashlib.sha256(password.encode()).hexdigest()

        # ✅ GET the full DB path safely from Django settings
        db_path = settings.DATABASES['default']['NAME']
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # INSERT user into the Users table
        cursor.execute(
            "INSERT INTO Users (email, password_hash, full_name) VALUES (?, ?, ?)",
            (email, password_hash, full_name)
        )

        conn.commit()
        conn.close()

        return HttpResponse("✅ Account registered successfully!")

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

def calculator_results(request):
    return render(request, 'calculator_results.html')

# Step 2: Show the form for budget + target ratings
def calculator(request):
    if request.method == 'GET':
        # Use ClassTargets for class names and target ratings in the form
        class_targets_qs = ClassTargets.objects.all().values('class_name', 'target_rating')
        class_targets = [
            {'class': ct['class_name'], 'target_rating': ct['target_rating']}
            for ct in class_targets_qs
        ]
        return render(request, 'calculator.html', {'class_targets': class_targets})

    elif request.method == 'POST':
        global_budget = float(request.POST.get('global_budget', 1e6))

        # Extract per-class targets from POST data
        targets = {
            key[6:]: float(value)
            for key, value in request.POST.items()
            if key.startswith('class_')
        }

        # Fetch interventions grouped by class from DetailedMatrix
        interventions = (
            DetailedMatrix.objects
            .exclude(class_name__isnull=True)
            .exclude(intervention__isnull=True)
            .order_by('class_name', '-impact_rating')
        )

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
                'global_budget': global_budget
            }
        )
