import os
import pandas as pd
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
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


# Step 1: Home page with "Get Started" button
def create_project(request):
    return render(request, 'create_project.html')

@login_required(login_url='login')
def home(request):
    return render(request, 'home.html')

def projects_view(request):
    return render(request, 'projects.html', {}, content_type='text/html')

def dashboard_view(request):
    return render(request, 'dashboard.html')



def register_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('password')

       
        if not username or not email or not password:
            messages.error(request, "All fields are required.")
            return render(request, 'register.html')

        if User.objects.filter(username=username).exists():
            messages.error(request, "Username already exists.")
            return render(request, 'register.html')

        if User.objects.filter(email=email).exists():
            messages.error(request, "Email already exists.")
            return render(request, 'register.html')

        
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password
        )

        
        login(request, user)

        messages.success(request, "Registration successful!")
        return redirect('home')  

    return render(request, 'register.html')

    
    return render(request, 'register.html')


def login_view(request):
    if request.user.is_authenticated:
        return redirect('home') 

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            return redirect('home')
        else:
            messages.error(request, "Invalid username or password.")

    return render(request, 'login.html')


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
    
## settings page
@login_required
def settings_view(request):
    user = request.user
    current_theme = request.session.get('theme', 'light')

    if request.method == 'POST':
        try:
            # -------------------------
            # Theme change
            # -------------------------
            if 'theme' in request.POST:
                new_theme = request.POST.get('theme', 'light')
                request.session['theme'] = new_theme
                request.session.modified = True
                messages.success(request, f"Theme changed to {new_theme} mode!")
                return redirect('settings')

            # -------------------------
            # Profile info update
            # -------------------------
            if 'update_profile' in request.POST:
                new_username = request.POST.get('username')
                new_email = request.POST.get('email')

                if not new_username or not new_email:
                    raise ValueError("Username and email cannot be blank.")

                # Check if username/email already exists
                if User.objects.filter(username=new_username).exclude(id=user.id).exists():
                    raise ValueError("Username already exists.")
                if User.objects.filter(email=new_email).exclude(id=user.id).exists():
                    raise ValueError("Email already exists.")

                # Save updates
                user.username = new_username
                user.email = new_email
                user.save()
                messages.success(request, "Profile updated successfully!")

            # -------------------------
            # Password change
            # -------------------------
            if 'change_password' in request.POST:
                current_password = request.POST.get('current_password')
                new_password = request.POST.get('new_password')
                confirm_password = request.POST.get('confirm_password')

                if not current_password or not new_password or not confirm_password:
                    raise ValueError("All password fields are required.")

                if new_password != confirm_password:
                    raise ValueError("New passwords do not match.")

                if not user.check_password(current_password):
                    raise ValueError("Current password is incorrect.")

                # Set new password and keep user logged in
                user.set_password(new_password)
                user.save()
                from django.contrib.auth import update_session_auth_hash
                update_session_auth_hash(request, user)
                messages.success(request, "Password changed successfully!")

        except ValueError as ve:
            # Caught logical/user errors
            messages.error(request, f"Error: {ve}")
        except Exception as e:
            # Catch unexpected errors
            messages.error(request, "Unexpected error occurred. Please try again later.")
            # Optional: log the error
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Settings update failed: {e}")

        return redirect('settings')

    # GET request
    context = {
        'user': user,
        'current_theme': current_theme
    }
    return render(request, 'settings.html', context)
