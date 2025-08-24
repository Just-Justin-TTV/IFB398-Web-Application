import os
from django.shortcuts import render, redirect
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import ClassTargets, Interventions

# Home page
def create_project(request):
    return render(request, 'create_project.html')

@login_required(login_url='login')
def home(request):
    return render(request, 'home.html')

def projects_view(request):
    return render(request, 'projects.html', {}, content_type='text/html')

def dashboard_view(request):
    return render(request, 'dashboard.html')

# Authentication
def register_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password1 = request.POST.get('password1')
        password2 = request.POST.get('password2')

        if not username or not email or not password1 or not password2:
            messages.error(request, "All fields are required.")
            return render(request, 'register.html')
        if password1 != password2:
            messages.error(request, "Passwords do not match.")
            return render(request, 'register.html')
        if User.objects.filter(username=username).exists():
            messages.error(request, "Username already exists.")
            return render(request, 'register.html')
        if User.objects.filter(email=email).exists():
            messages.error(request, "Email already exists.")
            return render(request, 'register.html')

        user = User.objects.create_user(username=username, email=email, password=password1)
        login(request, user)
        messages.success(request, "Registration successful!")
        return redirect('home')

    return render(request, 'register.html')

def login_view(request):
    if request.user.is_authenticated:
        return redirect('home')
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user:
            login(request, user)
            return redirect('home')
        else:
            messages.error(request, "Invalid username or password.")
    return render(request, 'login.html')

def logout_view(request):
    if request.method == "POST":
        logout(request)
        messages.success(request, "You have successfully logged out.")
        return redirect('login')
    return redirect('home')

# Calculator
@login_required(login_url='login')
def calculator(request):
    if request.method == 'GET':
        class_targets_qs = ClassTargets.objects.all().values('class_name', 'target_rating')
        class_targets = [{'class': ct['class_name'], 'target_rating': ct['target_rating']} for ct in class_targets_qs]
        return render(request, 'calculator.html', {'class_targets': class_targets})

    elif request.method == 'POST':
        global_budget = float(request.POST.get('global_budget', 1e6))

        # Extract per-class targets
        targets = {key[6:]: float(value) for key, value in request.POST.items() if key.startswith('class_')}

        # Fetch interventions
        interventions = Interventions.objects.exclude(class_name__isnull=True).exclude(name__isnull=True).order_by('class_name')

        # Map cost_level to approximate cost
        cost_mapping = {1: 5000, 2: 10000, 3: 25000, 4: 50000, 5: 100000, 6: 200000, 7: 500000,
                        8: 1000000, 9: 2000000, 10: 5000000}

        # Group interventions by class and filter by budget
        grouped_results = {}
        for row in interventions:
            if row.cost_level is None:
                continue
            approx_cost = cost_mapping.get(row.cost_level, 0)
            if approx_cost <= global_budget:
                grouped_results.setdefault(row.class_name, []).append(row)

        # Optional: sort interventions by cost level
        for cls in grouped_results:
            grouped_results[cls].sort(key=lambda x: x.cost_level)

        return render(request, 'calculator_results.html', {
            'grouped_results': grouped_results,
            'global_budget': global_budget,
            'targets': targets
        })
