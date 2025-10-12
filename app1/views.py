import json
import logging
from decimal import Decimal, InvalidOperation
from typing import Optional, Any, Dict

from django.db import connection
from django.db.models import Q
from django.http import JsonResponse, HttpRequest, HttpResponse, HttpResponseBadRequest

from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import login, logout, authenticate, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import ensure_csrf_cookie
from django.contrib.auth.models import User
from typing import List, Dict
from .models import Interventions, InterventionDependencies, InterventionEffects, Metrics
from .models import Metrics, ClassTargets, Interventions, InterventionDependencies, User as AppUser
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

logger = logging.getLogger(__name__)


# =========================
# Helpers
# =========================

def _resolve_app_user(request: HttpRequest) -> Optional[AppUser]:
    user = getattr(request, "user", None)
    if not getattr(user, "is_authenticated", False):
        return None
    if getattr(user, "username", None):
        hit = AppUser.objects.filter(username=user.username).first()
        if hit:
            return hit
    if getattr(user, "email", None):
        hit = AppUser.objects.filter(email=user.email).first()
        if hit:
            return hit
    return None


def _num(value: Any, default: Optional[float] = None) -> Optional[float]:
    if value is None:
        return default
    s = str(value).strip().lower()
    s = s.replace("aud", "").replace(",", "").replace("k", "000").replace("–", "-").replace("%", "").strip()
    try:
        return float(s)
    except Exception:
        return default


def _to_dec(value: Any) -> Optional[Decimal]:
    if value in (None, "", "null"):
        return None
    try:
        return Decimal(str(value).replace(",", "").replace("%", ""))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _to_int(value: Any) -> Optional[int]:
    if value in (None, "", "null"):
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


# =========================
# Create Project
# =========================

@login_required(login_url='login')
def create_project(request: HttpRequest):
    if request.method == "POST":
        project_name = (request.POST.get("project_name") or "").strip()
        project_location = (request.POST.get("location") or request.POST.get("project_location") or "").strip()
        project_type = (request.POST.get("project_type") or "").strip()

        owner = request.user
        m = Metrics(user=owner, project_name=project_name, location=project_location, project_type=project_type)
        m.save()

        request.session["metrics_id"] = m.id
        my_ids = request.session.get("my_project_ids", [])
        if m.id not in my_ids:
            my_ids.append(m.id)
            request.session["my_project_ids"] = my_ids
            request.session.modified = True

        return redirect("carbon")

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
    ui_key = (request.GET.get("cls") or "").strip().lower()
    logger.info("interventions_api called with cls=%s", ui_key)

    project_id = request.session.get("project_id")
    metrics = {}
    try:
        with connection.cursor() as cur:
            cur.execute(
                'SELECT gifa_m2, building_footprint_m2 FROM "Metrics" WHERE project_id=%s',
                [project_id]
            )
            row = cur.fetchone()
            if row:
                metrics["gifa_m2"], metrics["building_footprint_m2"] = row
            else:
                metrics["gifa_m2"] = metrics["building_footprint_m2"] = 0
        logger.info("Fetched metrics: %s", metrics)
    except Exception as e:
        logger.exception("Error fetching metrics for project_id=%s", project_id)
        metrics["gifa_m2"] = metrics["building_footprint_m2"] = 0

    try:
        with connection.cursor() as cur:
            desc = connection.introspection.get_table_description(cur, "Interventions")
            colnames = [getattr(c, "name", getattr(c, "column_name", "")) for c in desc]
        logger.info("Columns in Interventions table: %s", colnames)
    except Exception as e:
        logger.exception("Failed to get table description for Interventions")
        colnames = []

    select_cols = ", ".join(f'"{c}"' if c.lower() == "class" else c for c in colnames)
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
    try:
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
                    "cost_level": obj.get("cost_level") or 0,
                    "intervention_rating": obj.get("intervention_rating") or 0,
                    "gifa_m2": metrics.get("gifa_m2", 0),
                    "building_footprint_m2": metrics.get("building_footprint_m2", 0),
                })
        logger.info("Fetched %d interventions", len(items))
    except Exception as e:
        logger.exception("Error fetching interventions from DB")

    return JsonResponse({"items": items})


# =========================
# Save Metrics
# =========================

@require_POST
@login_required(login_url='login')
def save_metrics(request: HttpRequest) -> JsonResponse:
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
        logger.info("Created new Metrics object for user %s", m.user)

    numeric_fields = [
        "roof_area_m2", "roof_percent_gifa", "basement_size_m2", "basement_percent_gifa",
        "num_apartments", "num_keys", "num_wcs", "gifa_m2", "external_wall_area_m2",
        "external_openings_m2", "building_footprint_m2", "estimated_auto_budget_aud"
    ]
    for field in numeric_fields:
        if hasattr(m, field):
            value = _to_dec(payload.get(field))
            setattr(m, field, value)
            logger.debug("Set %s=%s", field, value)

    if hasattr(m, "building_type"):
        m.building_type = payload.get("building_type") or getattr(m, "building_type", None)
    if hasattr(m, "basement_present"):
        m.basement_present = bool(payload.get("basement_present"))

    if not m.user:
        m.user = _resolve_app_user(request)

    m.save()
    request.session["metrics_id"] = m.id
    logger.info("Metrics saved with id=%s", m.id)

    return JsonResponse({"ok": True, "metrics_id": m.id})


# =========================
# Carbon / Calculator Views
# =========================

@login_required
def carbon_view(request):
    interventions = Interventions.objects.all()
    interventions_dict = {}

    CLASS_ALIASES_REVERSE = {}
    for key, aliases in CLASS_ALIASES.items():
        for a in aliases:
            CLASS_ALIASES_REVERSE[a.lower()] = key

    for i in interventions:
        # Map database theme to UI class key
        db_theme = (i.theme or "Other").lower()
        cls_key = CLASS_ALIASES_REVERSE.get(db_theme, "other")

        interventions_dict.setdefault(cls_key, []).append({
            "id": i.id,
            "name": i.name or f"Intervention #{i.id}",
            "cost": float(i.cost_level or 0),
            "rating": float(i.intervention_rating or 0),
            "badges": [i.theme.capitalize()] if i.theme else [],
        })

    classes = [
        {"key": "carbon", "label": "Carbon", "target": 80},
        {"key": "health", "label": "Health & Wellbeing", "target": 60},
        {"key": "water", "label": "Water Use", "target": 30},
        {"key": "circular", "label": "Circular Economy", "target": 40},
        {"key": "resilience", "label": "Resilience", "target": 60},
        {"key": "value", "label": "Value & Cost", "target": 10},
        {"key": "biodiversity", "label": "Biodiversity", "target": 20},
        {"key": "other", "label": "Other", "target": 0},
    ]

    import json
    interventions_json = json.dumps(interventions_dict)

    return render(request, "carbon.html", {
        "interventions_json": interventions_json,
        "classes": classes,
    })


def intervention_effects(metric, interventions, selected_ids=None):
    """
    Adjust intervention ratings based on dependencies/effects.
    """
    sel_ids = set(int(s) for s in (selected_ids or []))
    updated_ratings = {}

    for effect in InterventionEffects.objects.all():
        source_name = (effect.source_intervention_name or "").strip().lower()
        target_name = (effect.target_intervention_name or "").strip().lower()
        value = Decimal(effect.effect_value or 0)

        source = next((i for i in interventions if (i.name or "").strip().lower() == source_name), None)
        target = next((i for i in interventions if (i.name or "").strip().lower() == target_name), None)

        if source and target and source.id in sel_ids:
            target.intervention_rating = max(Decimal("0"), Decimal(target.intervention_rating or 0) + value)
            target.save(update_fields=["intervention_rating"])
            updated_ratings[target.id] = float(target.intervention_rating)

    return interventions, updated_ratings


# =========================
# Calculator view
# =========================
# =========================
# Calculator view
# =========================
@login_required
@csrf_exempt  # if you want to skip CSRF for testing, otherwise remove
def calculator(request):
    """
    Handles GET/POST for the calculator page.
    GET: renders template
    POST: accepts JSON or form-encoded payload
    """
    if request.method == "POST":
        return _process_calculator_post(request)
    # GET request just renders page
    return render(request, "calculator.html")


def _process_calculator_post(request):
    """
    Process POST requests to the calculator endpoint.
    Handles both form data and JSON payloads.
    """

    # Try to get JSON payload first
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        # Fallback to form POST data
        payload = request.POST

    # Get metric ID (support both keys)
    metric_id = payload.get("metric_id") or payload.get("metrics_id")
    if not metric_id:
        logger.warning("No metric ID provided in request")
        return JsonResponse({"error": "Metric ID missing"}, status=400)

    # Fetch metric from DB
    metric = Metrics.objects.filter(id=metric_id).first()
    if not metric:
        logger.warning("Metric not found for id=%s", metric_id)
        return JsonResponse({"error": "Metric not found"}, status=400)

    # Get selected interventions (if any)
    selected_ids = payload.get("selected_ids") or []
    if isinstance(selected_ids, str):
        # If sent as comma-separated string
        selected_ids = [int(i.strip()) for i in selected_ids.split(",") if i.strip().isdigit()]
    else:
        # Ensure integers
        selected_ids = [int(i) for i in selected_ids]

    # Get global budget (optional)
    try:
        global_budget = float(payload.get("global_budget", 0))
    except ValueError:
        global_budget = 0

    logger.info(
        "Processing calculator for metric_id=%s, selected_ids=%s, global_budget=%s",
        metric_id,
        selected_ids,
        global_budget,
    )

    # Example: calculate result (replace with your actual logic)
    result = metric.value * len(selected_ids)  # dummy calculation

    return JsonResponse({
        "success": True,
        "metric_id": metric_id,
        "selected_ids": selected_ids,
        "global_budget": global_budget,
        "result": result
    })






# =========================
# Project List / Detail
# =========================

@login_required(login_url='login')
def projects_view(request: HttpRequest):
    q = (request.GET.get("q") or "").strip()
    ids = request.session.get("my_project_ids", [])
    qs = Metrics.objects.filter(id__in=ids).order_by("-updated_at", "-created_at")
    if q:
        qs = qs.filter(Q(project_name__icontains=q) | Q(project_type__icontains=q) | Q(location__icontains=q))
    return render(request, "projects.html", {"projects": qs, "query": q})


@login_required(login_url='login')
@login_required(login_url='login')
def project_detail_view(request, pk: int):
    p = Metrics.objects.filter(id=pk).first()
    if not p:
        return redirect("projects")

    session_ids = set(request.session.get("my_project_ids", []))
    is_owner = (p.user_id == getattr(request.user, "id", None))
    if not is_owner and pk not in session_ids:
        return redirect("projects")

    can_edit = request.GET.get("edit") == "1"   # <-- THIS LINE
    request.session["metrics_id"] = p.id
    request.session.modified = True
    return render(request, "project_detail.html", {"p": p, "can_edit": can_edit})



# =========================
# Authentication + Settings
# =========================

def login_view(request: HttpRequest):
    if request.user.is_authenticated:
        return redirect("home")
    if request.method == "POST":
        user = authenticate(request, username=request.POST.get("username"), password=request.POST.get("password"))
        if user:
            login(request, user)
            return redirect("home")
        messages.error(request, "Invalid username or password.")
    return render(request, "login.html")


def logout_view(request: HttpRequest):
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


@login_required(login_url='login')
def settings_view(request: HttpRequest):
    user = request.user
    current_theme = request.session.get("theme", "light")

    if request.method == "POST":
        try:
            # Theme update
            if "theme" in request.POST:
                new_theme = request.POST.get("theme", "light")
                request.session["theme"] = new_theme
                request.session.modified = True
                messages.success(request, f"Theme changed to {new_theme} mode!")

            # Profile update
            elif "update_profile" in request.POST:
                new_username = request.POST.get("username")
                new_email = request.POST.get("email")
                if not new_username or not new_email:
                    raise ValueError("Username and email cannot be blank.")
                if User.objects.filter(username=new_username).exclude(id=user.id).exists():
                    raise ValueError("Username already exists.")
                if User.objects.filter(email=new_email).exclude(id=user.id).exists():
                    raise ValueError("Email already exists.")
                user.username = new_username
                user.email = new_email
                user.save()
                messages.success(request, "Profile updated successfully!")

            # Password change
            elif "change_password" in request.POST:
                current_password = request.POST.get("current_password")
                new_password = request.POST.get("new_password")
                confirm_password = request.POST.get("confirm_password")
                if not all([current_password, new_password, confirm_password]):
                    raise ValueError("All password fields are required.")
                if new_password != confirm_password:
                    raise ValueError("New passwords do not match.")
                if not user.check_password(current_password):
                    raise ValueError("Current password is incorrect.")
                user.set_password(new_password)
                user.save()
                update_session_auth_hash(request, user)
                messages.success(request, "Password changed successfully!")

        except ValueError as ve:
            messages.error(request, f"Error: {ve}")
        except Exception as e:
            messages.error(request, "Unexpected error occurred. Please try again later.")
            logger.exception("Settings update failed")

        return redirect("settings")

    return render(request, "settings.html", {"user": user, "current_theme": current_theme})

@login_required(login_url='login')
def home(request):
    return render(request, 'home.html')

@login_required(login_url='login')
def calculator_results(request):
    cls = request.GET.get('cls', 'carbon')  # default class
    interventions_qs = Interventions.objects.filter(theme=cls).order_by('-intervention_rating', 'cost_level')
    
    # Convert queryset to JSON-serializable list
    interventions = []
    for i in interventions_qs:
        interventions.append({
            "id": str(i.id),
            "name": i.name,
            "theme": i.theme,
            "description": i.description,
            "cost_level": float(i.cost_level or 0),
            "intervention_rating": float(i.intervention_rating or 0),
            "cost_range": getattr(i, "cost_range", ""),
        })

    # Pass to template
    return render(request, "calculator_results.html", {
        "interventions_json": json.dumps(interventions),
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

@login_required(login_url='login')
def dashboard_view(request):
    # Show ONLY projects created in this browser session
    ids = request.session.get("my_project_ids", [])
    projects = Metrics.objects.filter(id__in=ids).order_by("-updated_at", "-created_at")

    # Keep it light on the dashboard (top 5)
    top_projects = list(projects[:5])

    return render(request, "dashboard.html", {
        "top_projects": top_projects,   # for Project Summary table
        "projects_count": projects.count(),
    })

@login_required(login_url='login')
def carbon_2_view(request):
    return render(request, 'carbon_2.html')


