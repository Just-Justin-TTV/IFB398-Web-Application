import os
from django.shortcuts import render, redirect
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import ClassTargets, Interventions, Metrics
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.http import JsonResponse, HttpResponseBadRequest
from django.contrib.auth import get_user
import json
from decimal import Decimal, InvalidOperation
from .models import Metrics, User as AppUser
from django.db import connection


# Home page
def create_project(request):
    return render(request, 'create_project.html')



# UI key -> possible DB labels/aliases
CLASS_ALIASES = {
    "carbon":      ["carbon", "carbon emissions", "operating carbon", "operational carbon", "embodied carbon"],
    "health":      ["health", "health & wellbeing", "health and wellbeing"],
    "water":       ["water", "water use", "water efficiency"],
    "circular":    ["circular", "circular economy"],
    "resilience":  ["resilience"],
    "biodiversity":["biodiversity"],
    "value":       ["value", "value & cost", "value and cost"],
}

@require_GET
def interventions_api(request):
    """
    GET /api/interventions/?cls=carbon
    Returns rows grouped by theme (front-end shows a header when theme changes)
    Fields: id, name, theme, description, cost_level, cost_range
    """
    ui_key = (request.GET.get("cls") or "").strip().lower()

    # Introspect available columns so we never crash on missing local columns
    with connection.cursor() as cur:
        desc = connection.introspection.get_table_description(cur, "Interventions")
        colnames = [getattr(c, "name", getattr(c, "column_name", "")) for c in desc]

    # Build SELECT *so we can include "extra" columns if needed*
    select_cols = ", ".join(f'"{c}"' if c.lower() in {"class"} else c for c in colnames)
    sql = f'SELECT {select_cols} FROM "Interventions"'
    params = []

    if ui_key:
        terms = CLASS_ALIASES.get(ui_key, [ui_key])
        # flexible WHERE: class LIKE any alias (case-insensitive)
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
                "cost_level": obj.get("cost_level") or 0,          # int if present
                "cost_range": obj.get("cost_range") or "",         # e.g., "10–25k AUD"
                # You can expose everything else if you need it on the client:
                # "extra": obj,
            })

    return JsonResponse({"items": items})

def _num(x, default=None):
    """
    Convert things like '73,560', '25.8%', '200–500k AUD' to a float.
    Returns default (None) if it can't parse.
    """
    if x is None:
        return default
    s = str(x).strip().lower()
    # normalize
    s = (s
         .replace('aud', '')
         .replace(',', '')
         .replace('k', '000')
         .replace('–', '-')  # en dash
         .replace('%', '')
         .strip())
    try:
        return float(s)
    except Exception:
        return default
    
def _resolve_app_user(request):
    """
    Try to find a matching app1.User from the authenticated Django auth user.
    Returns an AppUser instance or None.
    """
    u = getattr(request, "user", None)
    if not getattr(u, "is_authenticated", False):
        return None

    uname = getattr(u, "username", None)
    email = getattr(u, "email", None)

    if uname:
        found = AppUser.objects.filter(username=uname).first()
        if found:
            return found
    if email:
        found = AppUser.objects.filter(email=email).first()
        if found:
            return found
    return None


@require_POST
def save_metrics(request):
    """
    Create or update a Metrics row from JSON body.
    If 'metrics_id' is provided and exists, update it; else create new.
    """
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return HttpResponseBadRequest("Invalid JSON")

    # load or create
    metrics_id = payload.get("metrics_id")
    if metrics_id:
        m = Metrics.objects.filter(id=metrics_id).first()
        if not m:
            return JsonResponse({"ok": False, "error": "metrics_id not found"}, status=404)
    else:
        m = Metrics()

    # optional user attach
    if hasattr(request, "user") and request.user.is_authenticated:
        m.user = _resolve_app_user(request)

    # assign fields
    m.project_code = payload.get("project_code") or None
    m.building_type = payload.get("building_type") or ""

    m.roof_area_m2 = _num(payload.get("roof_area_m2"))
    m.roof_percent_gifa = _num(payload.get("roof_percent_gifa"))

    m.basement_present = bool(payload.get("basement_present"))
    m.basement_size_m2 = _num(payload.get("basement_size_m2"))
    m.basement_percent_gifa = _num(payload.get("basement_percent_gifa"))

    m.num_apartments = int(payload.get("num_apartments") or 0)
    m.num_keys       = int(payload.get("num_keys") or 0)
    m.num_wcs        = int(payload.get("num_wcs") or 0)

    m.gifa_m2 = _num(payload.get("gifa_m2"))
    m.external_wall_area_m2 = _num(payload.get("external_wall_area_m2"))
    m.external_openings_m2  = _num(payload.get("external_openings_m2"))
    m.building_footprint_m2 = _num(payload.get("building_footprint_m2"))

    m.estimated_auto_budget_aud = _num(payload.get("estimated_auto_budget_aud"))

    m.save()
    return JsonResponse({"ok": True, "metrics_id": m.id})


def calculator_results(request):
    # Replace 'carbon.html' with the template you want to render
    return render(request, 'calculator_results.html')

@login_required(login_url='login')
def carbon_view(request):
    if request.method == 'GET':
        class_targets_qs = ClassTargets.objects.all().values('class_name', 'target_rating')
        class_targets = [{'class': ct['class_name'], 'target_rating': ct['target_rating']} for ct in class_targets_qs]
        return render(request, 'carbon.html', {'class_targets': class_targets})

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

        return render(request, 'carbon_2.html', {
            'grouped_results': grouped_results,
            'global_budget': global_budget,
            'targets': targets
        })


def carbon_2_view(request):
    return render(request, 'carbon_2.html')


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
