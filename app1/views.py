# views.py
import os
import json
from decimal import Decimal, InvalidOperation

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import ensure_csrf_cookie
from django.http import JsonResponse, HttpResponseBadRequest
from django.db import connection
from .models import Metrics, ClassTargets, Interventions, User as AppUser
# pdf inports
from django.http import HttpResponse
from django.utils import timezone
#from reportlab.lib.pagesizes import letter, A4
#from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
#from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
#from reportlab.lib import colors
#from reportlab.lib.units import inch
#from io import BytesIO

def _resolve_app_user(request):
    u = getattr(request, "user", None)
    if not getattr(u, "is_authenticated", False):
        return None
    # Map Django auth user -> your app1.User by username/email
    if getattr(u, "username", None):
        hit = AppUser.objects.filter(username=u.username).first()
        if hit: return hit
    if getattr(u, "email", None):
        hit = AppUser.objects.filter(email=u.email).first()
        if hit: return hit
    return None


def _num(x, default=None):
    """
    Convert strings like '73,560', '25.8%', '200–500k AUD' to float.
    Used by API -> Metrics save.
    """
    if x is None:
        return default
    s = str(x).strip().lower()
    s = (
        s.replace("aud", "")
         .replace(",", "")
         .replace("k", "000")
         .replace("–", "-")   # en dash
         .replace("%", "")
         .strip()
    )
    try:
        return float(s)
    except Exception:
        return default


# ---------------------------
# Create Project (Page 1)
# ---------------------------

@login_required(login_url='login')
def create_project(request):
    """
    GET  -> show the create_project form.
    POST -> create a Metrics row with just project_name, project_location, project_type;
            put metrics_id in session; redirect to /carbon/.
    """
    if request.method == "POST":
        project_name     = (request.POST.get("project_name") or "").strip()
        project_location = (request.POST.get("location") or request.POST.get("project_location") or "").strip()
        project_type     = (request.POST.get("project_type") or "").strip()

        # create a new Metrics row
        m = Metrics(user=_resolve_app_user(request))

        # set ONLY the fields that actually exist on your model
        if hasattr(m, "project_name"):
            m.project_name = project_name
        elif hasattr(m, "name"):
            m.name = project_name

        if hasattr(m, "project_location"):
            m.project_location = project_location
        elif hasattr(m, "location"):
            m.location = project_location

        if hasattr(m, "project_type"):
            m.project_type = project_type

        m.save()
        # remember this row so carbon.html updates the same record
        request.session["metrics_id"] = m.id

        return redirect("carbon")

    # GET
    return render(request, "create_project.html")

# ---------- API the carbon page already calls to save building metrics ----------
def _to_dec(x):
    if x in (None, "", "null"):
        return None
    try:
        return Decimal(str(x).replace(",", "").replace("%", ""))
    except (InvalidOperation, ValueError, TypeError):
        return None

def _to_int(x):
    if x in (None, "", "null"):
        return None
    try:
        return int(x)
    except (ValueError, TypeError):
        return None


# ---------------------------
# Interventions API
# ---------------------------

CLASS_ALIASES = {
    "carbon":       ["carbon", "carbon emissions", "operating carbon", "operational carbon", "embodied carbon"],
    "health":       ["health", "health & wellbeing", "health and wellbeing"],
    "water":        ["water", "water use", "water efficiency"],
    "circular":     ["circular", "circular economy"],
    "resilience":   ["resilience"],
    "biodiversity": ["biodiversity"],
    "value":        ["value", "value & cost", "value and cost"],
}

@require_GET
def interventions_api(request):
    """
    GET /api/interventions/?cls=carbon
    Returns: id, name, theme, description, cost_level, cost_range
    """
    ui_key = (request.GET.get("cls") or "").strip().lower()

    # Introspect columns to avoid hard dependency issues
    with connection.cursor() as cur:
        desc = connection.introspection.get_table_description(cur, "Interventions")
        colnames = [getattr(c, "name", getattr(c, "column_name", "")) for c in desc]

    select_cols = ", ".join(f'"{c}"' if c.lower() in {"class"} else c for c in colnames)
    sql = f'SELECT {select_cols} FROM "Interventions"'
    params = []

    if ui_key:
        terms = CLASS_ALIASES.get(ui_key, [ui_key])
        like_parts = []
        for t in terms:
            like_parts.append('LOWER("class") LIKE LOWER(%s)')
            params.append(f"%{t}%")
        sql += " WHERE " + " OR ".join(like_parts)

    sql += " ORDER BY theme, name"

    items = []
    with connection.cursor() as cur:
        cur.execute(sql, params)
        cols = [c[0] for c in cur.description]
        for row in cur.fetchall():
            obj = dict(zip(cols, row))
            items.append({
                "id": obj.get("id"),
                "name": obj.get("name") or f"Intervention #{obj.get('id')}",
                "theme": obj.get("theme") or "",
                "description": obj.get("description") or "",
                "cost_level": obj.get("cost_level") or 0,
                "intervention_rating": obj.get("intervention_rating") or 0,
            })

    return JsonResponse({"items": items})


# ---------------------------
# API: Save/Update Metrics (Page 2 and beyond)
# ---------------------------

@require_POST
@login_required(login_url='login')
def save_metrics(request):
    """
    JSON POST to /api/metrics/save/
    Updates the SAME Metrics row created on create_project step.
    Uses metrics_id from payload OR session['metrics_id'].
    """
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return HttpResponseBadRequest("Invalid JSON")

    metrics_id = payload.get("metrics_id") or request.session.get("metrics_id")
    m = Metrics.objects.filter(id=metrics_id).first() if metrics_id else None
    if not m:
        # If a user jumped here directly, create a fresh row so we don't 500
        m = Metrics(user=_resolve_app_user(request))

    # ---- do NOT touch project_* fields here ----
    # Only update building metrics
    if hasattr(m, "building_type"):
        m.building_type             = payload.get("building_type") or getattr(m, "building_type", None)
    if hasattr(m, "roof_area_m2"):
        m.roof_area_m2              = _to_dec(payload.get("roof_area_m2"))
    if hasattr(m, "roof_percent_gifa"):
        m.roof_percent_gifa         = _to_dec(payload.get("roof_percent_gifa"))
    if hasattr(m, "basement_present"):
        m.basement_present          = bool(payload.get("basement_present"))
    if hasattr(m, "basement_size_m2"):
        m.basement_size_m2          = _to_dec(payload.get("basement_size_m2"))
    if hasattr(m, "basement_percent_gifa"):
        m.basement_percent_gifa     = _to_dec(payload.get("basement_percent_gifa"))
    if hasattr(m, "num_apartments"):
        m.num_apartments            = _to_int(payload.get("num_apartments"))
    if hasattr(m, "num_keys"):
        m.num_keys                  = _to_int(payload.get("num_keys"))
    if hasattr(m, "num_wcs"):
        m.num_wcs                   = _to_int(payload.get("num_wcs"))
    if hasattr(m, "gifa_m2"):
        m.gifa_m2                   = _to_dec(payload.get("gifa_m2"))
    if hasattr(m, "external_wall_area_m2"):
        m.external_wall_area_m2     = _to_dec(payload.get("external_wall_area_m2"))
    if hasattr(m, "external_openings_m2"):
        m.external_openings_m2      = _to_dec(payload.get("external_openings_m2"))
    if hasattr(m, "building_footprint_m2"):
        m.building_footprint_m2     = _to_dec(payload.get("building_footprint_m2"))
    if hasattr(m, "estimated_auto_budget_aud"):
        m.estimated_auto_budget_aud = _to_dec(payload.get("estimated_auto_budget_aud"))

    if not m.user:
        m.user = _resolve_app_user(request)

    m.save()
    request.session["metrics_id"] = m.id
    return JsonResponse({"ok": True, "metrics_id": m.id})

# ---------------------------
# Carbon / Calculator pages
# ---------------------------

@ensure_csrf_cookie
@login_required(login_url='login')
def carbon_view(request):
    """
    GET  -> render carbon.html with:
            - class_targets (for the targets form)
            - active_metrics_id (the Metrics row we’re editing)
            - project (project_name, project_location, project_type) pulled
              from that Metrics row so you can show it under the header.
    POST -> your existing budget/targets flow to carbon_2.html
    """
    if request.method == 'GET':
        class_targets_qs = ClassTargets.objects.all().values('class_name', 'target_rating')
        class_targets = [
            {'class': ct['class_name'], 'target_rating': ct['target_rating']}
            for ct in class_targets_qs
        ]

        # NEW: load project info from the same Metrics row created on the previous page
        metrics_id = request.session.get('metrics_id')
        project = None
        if metrics_id:
            project = (Metrics.objects
                       .filter(id=metrics_id)
                       .values('project_name', 'location', 'project_type')
                       .first())

        return render(
            request,
            'carbon.html',
            {
                'class_targets': class_targets,
                'active_metrics_id': metrics_id,
                'project': project,  # <-- use {{ project.project_name }}, etc. in carbon.html
            }
        )

    # POST -> unchanged (your generate interventions flow)
    global_budget = float(request.POST.get('global_budget', 1e6))
    targets = {
        key[6:]: float(value)
        for key, value in request.POST.items()
        if key.startswith('class_')
    }

    interventions = (
        Interventions.objects
        .exclude(class_name__isnull=True)
        .exclude(name__isnull=True)
        .order_by('class_name')
    )

    cost_mapping = {
        1: 5000, 2: 10000, 3: 25000, 4: 50000, 5: 100000,
        6: 200000, 7: 500000, 8: 1000000, 9: 2000000, 10: 5000000
    }

    grouped_results = {}
    for row in interventions:
        if row.cost_level is None:
            continue
        approx_cost = cost_mapping.get(row.cost_level, 0)
        if approx_cost <= global_budget:
            grouped_results.setdefault(row.class_name, []).append(row)

    for cls in grouped_results:
        grouped_results[cls].sort(key=lambda x: x.cost_level)

    return render(
        request,
        'carbon_2.html',
        {
            'grouped_results': grouped_results,
            'global_budget': global_budget,
            'targets': targets,
        }
    )

def carbon_2_view(request):
    return render(request, 'carbon_2.html')


@login_required(login_url='login')
def calculator(request):
    if request.method == 'GET':
        class_targets_qs = ClassTargets.objects.all().values('class_name', 'target_rating')
        class_targets = [
            {'class': ct['class_name'], 'target_rating': ct['target_rating']}
            for ct in class_targets_qs
        ]
        return render(request, 'calculator.html', {'class_targets': class_targets})

    global_budget = float(request.POST.get('global_budget', 1e6))
    targets = {key[6:]: float(value) for key, value in request.POST.items() if key.startswith('class_')}

    interventions = (
        Interventions.objects
        .exclude(class_name__isnull=True)
        .exclude(name__isnull=True)
        .order_by('class_name')
    )

    cost_mapping = {
        1: 5000, 2: 10000, 3: 25000, 4: 50000, 5: 100000,
        6: 200000, 7: 500000, 8: 1000000, 9: 2000000, 10: 5000000
    }

    grouped_results = {}
    for row in interventions:
        if row.cost_level is None:
            continue
        approx_cost = cost_mapping.get(row.cost_level, 0)
        if approx_cost <= global_budget:
            grouped_results.setdefault(row.class_name, []).append(row)

    for cls in grouped_results:
        grouped_results[cls].sort(key=lambda x: x.cost_level)

    return render(
        request,
        'calculator_results.html',
        {
            'grouped_results': grouped_results,
            'global_budget': global_budget,
            'targets': targets
        }
    )


def calculator_results(request):
    return render(request, 'calculator_results.html')


# ---------------------------
# Basic pages / auth
# ---------------------------

@login_required(login_url='login')
def home(request):
    return render(request, 'home.html')


def projects_view(request):
    return render(request, 'projects.html', {}, content_type='text/html')


def dashboard_view(request):
    return render(request, 'dashboard.html')


def register_view(request):
    if request.method == 'POST':
        username  = request.POST.get('username')
        email     = request.POST.get('email')
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

## reports page
@login_required(login_url='login')
def reports_page(request):
    # Show ALL projects without user filtering
    try:
        projects = Metrics.objects.all()
        
        projects_with_metrics = []
        for project in projects:
            projects_with_metrics.append({
                'id': project.id,
                'project_name': getattr(project, 'project_name', 'Unnamed Project'),
                'location': getattr(project, 'location', 'Unknown Location'),
                'project_type': getattr(project, 'project_type', 'Unknown Type'),
                'created_at': getattr(project, 'created_at', 'Unknown Date'),
                'metrics': project
            })
        
        context = {
            'projects': projects_with_metrics
        }
        return render(request, 'reports.html', context)
    except Exception as e:
        print(f"Error in reports_page: {e}")
        context = {
            'projects': []
        }
        return render(request, 'reports.html', context)

def generate_pdf_report(request, context, project):
    """Generate actual PDF report"""
    try:
        # For now, create a proper PDF using reportlab (you need to install it first)
        # pip install reportlab
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas
        from io import BytesIO
        
        # Create a file-like buffer to receive PDF data
        buffer = BytesIO()
        
        # Create the PDF object, using the buffer as its "file"
        p = canvas.Canvas(buffer, pagesize=letter)
        
        # Set up the PDF content
        p.setFont("Helvetica-Bold", 16)
        p.drawString(100, 750, f"PROJECT REPORT: {project.project_name}")
        
        p.setFont("Helvetica", 12)
        p.drawString(100, 730, f"Location: {project.location}")
        p.drawString(100, 710, f"Type: {project.project_type}")
        p.drawString(100, 690, f"Report Date: {timezone.now().strftime('%Y-%m-%d')}")
        
        # Add building metrics
        p.drawString(100, 650, "BUILDING METRICS:")
        p.drawString(120, 630, f"GIFA: {getattr(project, 'gifa_m2', 'N/A')} m²")
        p.drawString(120, 610, f"Roof Area: {getattr(project, 'roof_area_m2', 'N/A')} m²")
        p.drawString(120, 590, f"Building Type: {getattr(project, 'building_type', 'N/A')}")
        
        # Add financial overview
        p.drawString(100, 550, f"Budget: ${context.get('global_budget', 0):,}")
        p.drawString(100, 530, f"Budget Utilization: {context.get('budget_utilization', 0)}%")
        
        p.showPage()
        p.save()
        
        # FileResponse sets the Content-Disposition header so that browsers
        # present the option to save the file.
        buffer.seek(0)
        response = HttpResponse(buffer, content_type='application/pdf')
        filename = f"{project.project_name.replace(' ', '_')}_Report.pdf"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
        
    except ImportError:
        # Fallback if reportlab is not installed
        response = HttpResponse(content_type='application/pdf')
        filename = f"{project.project_name.replace(' ', '_')}_Report.pdf"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        response.write("%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >>\nendobj\n4 0 obj\n<< /Length 44 >>\nstream\nBT /F1 12 Tf 100 700 Td (PDF generation requires reportlab) Tj ET\nendstream\nendobj\nxref\n0 5\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n0000000233 00000 n \ntrailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n307\n%%EOF")
        return response
    except Exception as e:
        # Ultimate fallback - text file
        response = HttpResponse(content_type='text/plain')
        filename = f"{project.project_name}_Report.txt"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        report_content = f"""
        SUSTAINABILITY ANALYSIS REPORT
        ==============================
        
        Project: {project.project_name}
        Location: {project.location}
        Type: {project.project_type}
        
        BUILDING METRICS:
        - GIFA: {getattr(project, 'gifa_m2', 'N/A')} m²
        - Roof Area: {getattr(project, 'roof_area_m2', 'N/A')} m²
        - Building Type: {getattr(project, 'building_type', 'N/A')}
        
        FINANCIAL OVERVIEW:
        - Budget: ${context.get('global_budget', 0):,}
        - Budget Utilization: {context.get('budget_utilization', 0)}%
        
        Report generated by Sustainable Design Tool
        """
        
        response.write(report_content)
        return response
def generate_word_report(request, context, project):
    """Generate Word document version of the report"""
    try:
        # Try to use python-docx if available
        from docx import Document
        
        doc = Document()
        doc.add_heading(f'Project Report: {project.project_name}', 0)
        
        # Add project details
        doc.add_heading('Project Details', level=1)
        doc.add_paragraph(f'Location: {project.location}')
        doc.add_paragraph(f'Type: {project.project_type}')
        doc.add_paragraph(f'Report Date: {timezone.now().strftime("%Y-%m-%d")}')
        
        # Add building metrics
        doc.add_heading('Building Metrics', level=1)
        doc.add_paragraph(f'GIFA: {getattr(project, "gifa_m2", "N/A")} m²')
        doc.add_paragraph(f'Roof Area: {getattr(project, "roof_area_m2", "N/A")} m²')
        doc.add_paragraph(f'Building Type: {getattr(project, "building_type", "N/A")}')
        
        # Add financial overview
        doc.add_heading('Financial Overview', level=1)
        doc.add_paragraph(f'Budget: ${context.get("global_budget", 0):,}')
        doc.add_paragraph(f'Budget Utilization: {context.get("budget_utilization", 0)}%')
        
        doc.add_paragraph('Report generated by Sustainable Design Tool')
        
        response = HttpResponse(
            content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        )
        filename = f"{project.project_name.replace(' ', '_')}_Report.docx"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        doc.save(response)
        return response
        
    except ImportError:
        # Fallback - create a simple text file
        response = HttpResponse(content_type='text/plain')
        filename = f"{project.project_name}_Report.txt"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        report_content = f"""
        PROJECT REPORT - {project.project_name}
        
        Location: {project.location}
        Type: {project.project_type}
        
        Building Metrics:
        - GIFA: {getattr(project, 'gifa_m2', 'N/A')} m²
        - Roof Area: {getattr(project, 'roof_area_m2', 'N/A')} m²
        - Building Type: {getattr(project, 'building_type', 'N/A')}
        
        Financial Overview:
        - Budget: ${context.get('global_budget', 0):,}
        - Budget Utilization: {context.get('budget_utilization', 0)}%
        
        Note: Word document generation requires python-docx package
        """
        
        response.write(report_content)
        return response

def generate_report(request, project_id):
    # Use Metrics instead of Project
    project = get_object_or_404(Metrics, id=project_id)
    
    # Check if download is requested FIRST
    download_format = request.GET.get('download', None)
    
    # Get interventions data - using mock data for now
    interventions_by_class = {
        'Energy Efficiency': [
            {'name': 'Solar PV Installation', 'cost_level': 'Medium', 'cost_range': '$50,000-$100,000', 'impact_rating': 8},
            {'name': 'LED Lighting Upgrade', 'cost_level': 'Low', 'cost_range': '$5,000-$15,000', 'impact_rating': 7},
        ],
        'Water Management': [
            {'name': 'Rainwater Harvesting', 'cost_level': 'Medium', 'cost_range': '$20,000-$40,000', 'impact_rating': 6},
        ]
    }
    
    global_budget = 1000000
    interventions_count = sum(len(interventions) for interventions in interventions_by_class.values())
    
    # Calculate ratios and percentages
    openings_ratio = 0
    if project and project.external_wall_area_m2 and project.external_openings_m2:
        openings_ratio = (project.external_openings_m2 / project.external_wall_area_m2 * 100)
    
    budget_utilization = 65
    
    context = {
        'project': project,
        'metrics': project,  # Same as project since Metrics contains all data
        'interventions_by_class': interventions_by_class,
        'global_budget': global_budget,
        'openings_ratio': round(openings_ratio, 1),
        'budget_utilization': budget_utilization,
        'interventions_count': interventions_count
    }
    
    # Handle downloads FIRST
    if download_format == 'pdf':
        return generate_pdf_report(request, context, project)
    elif download_format == 'word':
        return generate_word_report(request, context, project)
    
    # Normal HTML view (only if no download requested)
    return render(request, 'report_template.html', context)

def project_detail(request, project_id):
    # Use Metrics instead of Project
    project = get_object_or_404(Metrics, id=project_id)
    return render(request, 'project_detail.html', {'project': project})