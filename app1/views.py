import os
import pandas as pd
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings

# Load Excel data once
excel_path = os.path.join(settings.BASE_DIR, 'app1/static/P2035-Sustainability Cost Matrix-240927-MASTER WIP-Rev.3.xlsx')
excel_file = pd.ExcelFile(excel_path)

# Load relevant sheets from the Excel file
matrix_sheet = excel_file.parse('Matrix')
detailed_matrix = excel_file.parse('Detailed Matrix', skiprows=2)

# Clean the detailed matrix by dropping rows and columns with all NaN values
matrix = detailed_matrix.dropna(how='all').dropna(axis=1, how='all')

# Extract relevant data for class targets (assuming rows 10-40 and columns 0, 2)
class_targets_df = matrix_sheet.iloc[10:40, [0, 2]].dropna()
class_targets_df.columns = ['Class', 'Target Rating']
class_targets_df['Target Rating'] = pd.to_numeric(class_targets_df['Target Rating'], errors='coerce')
class_targets_df = class_targets_df.dropna().reset_index(drop=True)

def home(request):
    # Prepare data for the index view (Home Page)
    return render(request, 'home.html')  # Home page view

@csrf_exempt
def calculator(request):
    # Calculator (index) page, where user submits budget and priorities
    if request.method == 'POST':
        global_budget = float(request.POST.get('global_budget', 1e6))
        priorities = {
            key[6:]: int(value)
            for key, value in request.POST.items() if key.startswith('class_')
        }

        total_priority = sum(priorities.values())
        IMPACT_SCALE = 20
        results = {}

        for cls, priority in priorities.items():
            if priority == 0:
                results[cls] = []
                continue

            class_budget = (priority / total_priority) * global_budget
            class_target_impact = priority * IMPACT_SCALE

            # Filter matrix for interventions based on class
            class_interventions = matrix[matrix['Class'].str.upper() == cls.upper()].copy()
            class_interventions = class_interventions[class_interventions['Impact Rating'].notna()]
            class_interventions = class_interventions.sort_values(by='Impact Rating', ascending=False)

            selected = []
            impact_acc = 0
            cost_acc = 0

            for _, row in class_interventions.iterrows():
                impact = row['Impact Rating']
                cost = row['Low Cost.1'] if pd.notna(row['Low Cost.1']) else 0

                if cost_acc + cost > class_budget:
                    continue

                selected.append(row)
                impact_acc += impact
                cost_acc += cost

                if impact_acc >= class_target_impact:
                    break

            if selected:
                df = pd.DataFrame(selected)
                results[cls] = df[[ 
                    'Theme', 'Interventions', 'Intervention Description',
                    'Impact Rating', 'Low Cost.1', 'High Cost.1'
                ]].rename(columns={
                    'Interventions': 'Intervention',
                    'Intervention Description': 'Description',
                    'Low Cost.1': 'Low Cost',
                    'High Cost.1': 'High Cost'
                }).to_dict(orient='records')
            else:
                results[cls] = []

        return render(request, 'calculator_results.html', {'grouped_results': results})  # Results page
    else:
        class_targets = class_targets_df.to_dict(orient='records')
        return render(request, 'calculator.html', {'class_targets': class_targets})  # Calculator page
