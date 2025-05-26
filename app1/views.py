import os
import pandas as pd
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.shortcuts import render

# Step 1: Home page with "Get Started" button
def create_project(request):
    return render(request, 'create_project.html')

def home(request):
    return render(request, 'home.html')

def projects_view(request):
    return render(request, 'projects.html', {}, content_type='text/html')

def dashboard_view(request):
    return render(request, 'dashboard.html')


def register_view(request):
    return render(request, 'register.html')

def login_view(request):
    return render(request, 'login.html')

# Step 1: Home page
def home(request):
    return render(request, 'home.html')

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
            DetailedMatrix.objects
            .exclude(class_name__isnull=True)
            .exclude(intervention__isnull=True)
            .order_by('class_name', '-impact_rating')
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
