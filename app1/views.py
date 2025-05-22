from django.shortcuts import render
from .models import DetailedMatrix, ClassTargets

# Step 1: Home page with "Get Started" button
def home(request):
    return render(request, 'home.html')

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
