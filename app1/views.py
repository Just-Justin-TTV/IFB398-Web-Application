# views.py
import os
import json
from decimal import Decimal, InvalidOperation

from django.db import connection
from django.db.models import Q

from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import login, logout, authenticate, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import ClassTargets, Interventions, Metrics
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import ensure_csrf_cookie
from django.contrib.auth.models import User  # Django auth user
from django.http import HttpRequest
from typing import Optional, List
from django.http import HttpRequest, HttpResponse, JsonResponse




from .models import (
    Metrics,
    ClassTargets,
    Interventions,
    User as AppUser,   # your app's user record that Metrics.user can point to
)

# =========================
# Helpers
# =========================

def _resolve_app_user(request):
    """Map Django auth user -> your app1.User row by username/email."""
    u = getattr(request, "user", None)
    if not getattr(u, "is_authenticated", False):
        return None
    if getattr(u, "username", None):
        hit = AppUser.objects.filter(username=u.username).first()
        if hit:
            return hit
    if getattr(u, "email", None):
        hit = AppUser.objects.filter(email=u.email).first()
        if hit:
            return hit
    return None


def _num(x, default=None):
    """
    Convert strings like '73,560', '25.8%', '200–500k AUD' to float.
    Useful if you ever parse free-text numeric inputs.
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


# =========================
# Create Project (Page 1)
# =========================

def create_project(request):
    """
    GET  -> show the create_project form.
    POST -> create a Metrics row, remember its ID in session for listing,
            then redirect to /carbon/.
    """
    if request.method == "POST":
        project_name     = (request.POST.get("project_name") or "").strip()
        project_location = (request.POST.get("location") or request.POST.get("project_location") or "").strip()
        project_type     = (request.POST.get("project_type") or "").strip()

        # owner only if authenticated; otherwise None
        owner = request.user if getattr(request.user, "is_authenticated", False) else None
        m = Metrics(user=owner)

        # set fields that exist on your Metrics model
        m.project_name = project_name
        m.location     = project_location
        m.project_type = project_type

        m.save()

        # remember this row for carbon page
        request.session["metrics_id"] = m.id

        # also remember it for the Projects listing (session-scoped)
        my_ids = request.session.get("my_project_ids", [])
        if m.id not in my_ids:
            my_ids.append(m.id)
            request.session["my_project_ids"] = my_ids
            request.session.modified = True

        return redirect("carbon")

    # GET
    return render(request, "create_project.html")

# =========================
# Interventions API
# =========================

CLASS_ALIASES = {
    "carbon": ["carbon", "carbon emissions", "operating carbon", "operational carbon", "embodied carbon"],
    "health": ["health", "health & wellbeing", "health and wellbeing"],
    "water": ["water", "water use", "water efficiency"],
    "circular": ["circular", "circular economy"],
    "resilience": ["resilience"],
    "biodiversity": ["biodiversity"],
    "value": ["value", "value & cost", "value and cost"],
}


@require_GET
def interventions_api(request):
    """
    Returns interventions as JSON, optionally filtered by class/theme.
    Handles metrics for the current project to include in the response.
    """
    ui_key = (request.GET.get("cls") or "").strip().lower()
    logger.info("interventions_api called with cls=%s", ui_key)

    # Get metrics for current project
    project_id = request.session.get("project_id")
    metrics = {"gifa_m2": 0, "building_footprint_m2": 0}
    if project_id:
        try:
            metric_obj = Metrics.objects.filter(id=project_id).first()
            if metric_obj:
                metrics["gifa_m2"] = float(metric_obj.gifa_m2 or 0)
                metrics["building_footprint_m2"] = float(metric_obj.building_footprint_m2 or 0)
        except Exception as e:
            logger.exception("Error fetching metrics for project_id=%s", project_id)

    # Prepare SQL to fetch interventions
    try:
        with connection.cursor() as cur:
            # Get column names dynamically
            desc = connection.introspection.get_table_description(cur, "Interventions")
            colnames = [getattr(c, "name", getattr(c, "column_name", "")) for c in desc]

        # Quote 'class' column properly for SQL
        select_cols = ", ".join(f'"{c}"' if c.lower() == "class" else c for c in colnames)
        sql = f'SELECT {select_cols} FROM "Interventions"'
        params = []

        # Apply class/theme filtering
        if ui_key:
            terms = CLASS_ALIASES.get(ui_key, [ui_key])
            like_parts = []
            for t in terms:
                like_parts.append('LOWER("class") LIKE LOWER(%s)')
                params.append(f"%{t}%")
            sql += " WHERE " + " OR ".join(like_parts)

        sql += " ORDER BY theme, name"

        # Execute query
        items = []
        with connection.cursor() as cur:
            logger.info("Executing SQL: %s with params %s", sql, params)
            cur.execute(sql, params)
            cols = [c[0] for c in cur.description]
            for row in cur.fetchall():
                obj = dict(zip(cols, row))
                items.append({
                    "id": obj.get("id"),
                    "name": obj.get("name") or f"Intervention #{obj.get('id')}",
                    "theme": obj.get("theme") or "",
                    "description": obj.get("description") or "",
                    "cost_level": float(obj.get("cost_level") or 0),
                    "intervention_rating": float(obj.get("intervention_rating") or 0),
                    "gifa_m2": metrics.get("gifa_m2", 0),
                    "building_footprint_m2": metrics.get("building_footprint_m2", 0),
                })
        logger.info("Fetched %d interventions", len(items))
    except Exception as e:
        logger.exception("Error fetching interventions from DB")
        items = []

    return JsonResponse({"items": items})


# =========================
# API: Save/Update Metrics (page 2+)
# =========================

@require_POST
@login_required(login_url='login')
def save_metrics(request):
    """
    JSON POST to /api/metrics/save/
    Updates the same Metrics row created on create_project step.
    Uses metrics_id from payload OR session['metrics_id'].
    """
    try:
        payload = json.loads(request.body.decode("utf-8"))
        logger.info("save_metrics payload: %s", payload)
    except json.JSONDecodeError:
        logger.warning("Invalid JSON received")
        return HttpResponseBadRequest("Invalid JSON")

    metrics_id = payload.get("metrics_id") or request.session.get("metrics_id")
    m = Metrics.objects.filter(id=metrics_id).first() if metrics_id else None
    if not m:
        m = Metrics(user=_resolve_app_user(request))

    # Only update building metrics (do not overwrite project_* here)
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
    request.session["metrics_id"] = m.id
    return JsonResponse({"ok": True, "metrics_id": m.id})


# =========================
# Carbon / Calculator
# =========================

@ensure_csrf_cookie
@login_required(login_url='login')
def carbon_view(request):
    """
    GET: render carbon.html with targets, active metrics, and project header info.
    POST: your existing budget/targets -> carbon_2.html
    """
    if request.method == 'GET':
        class_targets_qs = ClassTargets.objects.all().values('class_name', 'target_rating')
        class_targets = [{'class': ct['class_name'], 'target_rating': ct['target_rating']} for ct in class_targets_qs]

        metrics_id = request.session.get('metrics_id')
        project = None
        if metrics_id:
            project = (Metrics.objects
                       .filter(id=metrics_id)
                       .values('project_name', 'location', 'project_type')
                       .first())

        return render(request, 'carbon.html', {
            'class_targets': class_targets,
            'active_metrics_id': metrics_id,
            'project': project,
        })

    # POST (unchanged budgeting flow)
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

    return render(request, 'carbon_2.html', {
        'grouped_results': grouped_results,
        'global_budget': global_budget,
        'targets': targets,
    })


@login_required(login_url='login')
def carbon_2_view(request):
    return render(request, 'carbon_2.html')


def get_intervention_effects(request):
    source_name = request.GET.get('source')
    if not source_name:
        return JsonResponse({'error': 'No source provided'}, status=400)

    effects = InterventionEffects.objects.filter(source_intervention_name=source_name)
    data = [
        {
            'target': e.target_intervention_name,
            'effect': e.effect_value,
            'note': e.note
        }
        for e in effects
    ]
    return JsonResponse({'effects': data})


@login_required(login_url='login')
def calculator(request: HttpRequest):
    """
    Handles the calculator page.
    GET: renders the form with class targets.
    POST: processes interventions and shows filtered results.
    """
    import json

    if request.method == "GET":
        class_targets = list(ClassTargets.objects.values("class_name", "target_rating"))
        return render(request, "calculator.html", {"class_targets": class_targets})

    # POST now renders the results page using the updated intervention_effects
    return _process_calculator_post(request)


def intervention_effects(metric, interventions, selected_ids: Optional[List[int]] = None):
    """
    Adjust intervention ratings dynamically based on metric values and selected interventions.
    Ratings are only increased for interventions after selection.
    """
    grouped_interventions = {}

    for i in interventions:
        include = True

        # Check dependencies for metric thresholds
        deps = InterventionDependencies.objects.filter(intervention_id=i.id)
        for dep in deps:
            val = getattr(metric, dep.metric_name, None)
            if val is None:
                continue
            try:
                val = Decimal(val)
            except Exception:
                continue
            if (dep.min_value is not None and val < dep.min_value) or \
               (dep.max_value is not None and val > dep.max_value):
                include = False
                break

        if not include:
            continue

        base_rating = float(i.intervention_rating or 0)
        adjusted_rating = base_rating

        # Metric-based adjustment (example: scale by roof area)
        if getattr(metric, "roof_area_m2", 0):
            adjusted_rating *= 1 + float(metric.roof_area_m2 or 0) / 1000

        # Only apply selection multiplier if this intervention is selected
        if selected_ids and i.id in selected_ids:
            adjusted_rating *= 1.1  # +10% rating for selection

        cls = i.theme or "Other"
        grouped_interventions.setdefault(cls, []).append({
            "id": str(i.id),
            "name": i.name or f"Intervention #{i.id}",
            "cost_level": float(i.cost_level or 0),
            "intervention_rating": round(adjusted_rating, 2),
            "description": i.description or "No description available",
            "stage": getattr(i, "stage", ""),
            "class_name": getattr(i, "class_name", ""),
            "theme": cls
        })

    return grouped_interventions






def _process_calculator_post(request: HttpRequest) -> HttpResponse:
    metric = Metrics.objects.filter(user=request.user).order_by("-created_at").first()
    if not metric:
        return render(request, "calculator_results.html", {"interventions": {}, "classes": []})

    interventions = Interventions.objects.all()
    grouped_interventions = intervention_effects(metric, interventions)

    return render(request, "calculator_results.html", {
        "interventions": grouped_interventions,
        "interventions_json": json.dumps(grouped_interventions),
        "classes": [
            {"key": "carbon", "label": "Carbon", "target": 80},
            {"key": "health", "label": "Health & Wellbeing", "target": 60},
            {"key": "water", "label": "Water Use", "target": 30},
            {"key": "circular", "label": "Circular Economy", "target": 40},
            {"key": "resilience", "label": "Resilience", "target": 60},
            {"key": "value", "label": "Value & Cost", "target": 10},
            {"key": "biodiversity", "label": "Biodiversity", "target": 20},
        ],
        "cap_high": 300000
    })


# =========================
# Projects (List + Detail)
# =========================

@login_required(login_url='login')
def projects_view(request):
    """
    List the current user's projects from Metrics.
    Supports ?q= search across name/type/location.
    """
    q = (request.GET.get("q") or "").strip()
    ids = request.session.get("my_project_ids", [])


    qs = Metrics.objects.filter(id__in=ids).order_by("-updated_at", "-created_at")

    if q:
        from django.db.models import Q
        qs = qs.filter(
            Q(project_name__icontains=q) |
            Q(project_type__icontains=q) |
            Q(location__icontains=q)
        )

    return render(request, "projects.html", {
        "projects": qs,
        "query": q
    })


@login_required(login_url='login')
def project_detail_view(request, pk: int):
    """
    Show a single project (Metrics row) for the current user.
    """
    p = Metrics.objects.filter(id=pk, user=request.user).first()
    if not p:
        return redirect("projects")

    return render(request, "project_detail.html", {"p": p})


# =========================
# Basic pages / auth
# =========================

@login_required(login_url='login')
def home(request):
    return render(request, 'home.html')


def dashboard_view(request):
    # Show ONLY projects created in this browser session
    ids = request.session.get("my_project_ids", [])
    projects = (Metrics.objects
                .filter(id__in=ids)
                .order_by("-updated_at", "-created_at"))

    # Keep it light on the dashboard (top 5)
    top_projects = list(projects[:5])

    return render(request, "dashboard.html", {
        "top_projects": top_projects,   # for Project Summary table
        "projects_count": projects.count(),
    })

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
        return redirect("home")
    if request.method == "POST":
        user = authenticate(request, username=request.POST.get("username"), password=request.POST.get("password"))
        if user:
            login(request, user)
            return redirect('home')
        messages.error(request, "Invalid username or password.")
    return render(request, 'login.html')


def logout_view(request):
    if request.method == "POST":
        logout(request)
        messages.success(request, "Logged out successfully.")
        return redirect("login")
    return redirect("home")


def register_view(request: HttpRequest):
    if request.method == "POST":
        username = request.POST.get("username")
        email = request.POST.get("email")
        password1 = request.POST.get("password1")
        password2 = request.POST.get("password2")

        if not all([username, email, password1, password2]):
            messages.error(request, "All fields are required.")
        elif password1 != password2:
            messages.error(request, "Passwords do not match.")
        elif User.objects.filter(username=username).exists():
            messages.error(request, "Username already exists.")
        elif User.objects.filter(email=email).exists():
            messages.error(request, "Email already exists.")
        else:
            user = User.objects.create_user(username=username, email=email, password=password1)
            login(request, user)
            messages.success(request, "Registration successful!")
            return redirect("home")
    return render(request, "register.html")


# Calculator
@login_required(login_url='login')
def settings_view(request):
    user = request.user
    current_theme = request.session.get("theme", "light")

    if request.method == "POST":
        try:
            # Theme change
            if 'theme' in request.POST:
                new_theme = request.POST.get('theme', 'light')
                request.session['theme'] = new_theme
                request.session.modified = True
                messages.success(request, f"Theme changed to {new_theme} mode!")
                return redirect('settings')

            # Profile info update
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

                user.username = new_username
                user.email = new_email
                user.save()
                messages.success(request, "Profile updated successfully!")

            # Password change
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

                user.set_password(new_password)
                user.save()
                update_session_auth_hash(request, user)  # keep user logged in
                messages.success(request, "Password changed successfully!")

        except ValueError as ve:
            messages.error(request, f"Error: {ve}")
        except Exception as e:
            messages.error(request, "Unexpected error occurred. Please try again later.")
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Settings update failed: {e}")

        return redirect('settings')

    # GET
    context = {
        'user': user,
        'current_theme': current_theme
    }
    return render(request, 'settings.html', context)