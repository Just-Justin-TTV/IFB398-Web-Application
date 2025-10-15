# app1/views.py
import json
import logging
from decimal import Decimal, InvalidOperation
from typing import Optional, Any, List
from django.urls import reverse
from django.utils.text import slugify
from django.db import connection
from django.db.models import Q
from django.http import (
    JsonResponse,
    HttpRequest,
    HttpResponse,
    HttpResponseBadRequest,
)
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import login, logout, authenticate, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST, require_GET
from django.contrib.auth.models import User

from .models import (
    Metrics,
    ClassTargets,
    Interventions,
    InterventionDependencies,
    User as AppUser,
    InterventionEffects,
)

logger = logging.getLogger(__name__)


# =========================
# Helpers
# =========================

def _resolve_app_user(request: HttpRequest) -> Optional[AppUser]:
    """Map the Django auth user to your AppUser row (by username/email)."""
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
    s = (
        s.replace("aud", "")
         .replace(",", "")
         .replace("k", "000")
         .replace("–", "-")
         .replace("%", "")
         .strip()
    )
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


def _unique_project_code(project_name: str) -> str:
    """
    Create a unique, readable slug for Metrics.project_code.
    Tries 'my-project', then 'my-project-2', 'my-project-3', ...
    """
    base = slugify(project_name) or "project"
    code = base
    n = 2
    while Metrics.objects.filter(project_code=code).exists():
        code = f"{base}-{n}"
        n += 1
    return code


# =========================
# Create & Edit Project  → saves to Metrics
# =========================

@login_required(login_url='login')
def create_project(request: HttpRequest):
    """
    Step 1 – basic project card.
    Creates a Metrics row (project_name, location, building_type) and
    then sends the user to the Building Metrics page.
    """
    if request.method == "POST":
        project_name    = (request.POST.get("project_name") or "").strip()
        project_location= (request.POST.get("location") or request.POST.get("project_location") or "").strip()
        project_type    = (request.POST.get("project_type") or "").strip()

        if not project_name:
            messages.error(request, "Project name is required.")
            return render(request, "create_project.html")

        code = _unique_project_code(project_name)
        m = Metrics.objects.create(
            user=_resolve_app_user(request),
            project_code=code,
            project_name=project_name,
            location=project_location,
            building_type=project_type,
        )

        # track in session so it shows on Projects & Dashboard
        ids = list(request.session.get("my_project_ids", []))
        if m.id not in ids:
            ids.append(m.id)
        request.session["my_project_ids"] = ids
        request.session["metrics_id"] = m.id
        request.session.modified = True

        # >>> go to the Building Metrics page
        return redirect("carbon")

    return render(request, "create_project.html")

@login_required(login_url='login')
def metrics_edit(request, pk: int):
    """
    Edit basic project info stored in Metrics (project_name, location, building_type).
    GET  -> renders the same form as create, prefilled
    POST -> saves and redirects to a detail page (or Projects if you prefer)
    """
    m = get_object_or_404(Metrics, pk=pk)

    # only owner or projects created in this session
    session_ids = set(request.session.get("my_project_ids", []))
    is_owner = (m.user_id == getattr(_resolve_app_user(request), "id", None))
    if not is_owner and m.id not in session_ids:
        return redirect("projects")

    if request.method == "POST":
        m.project_name = (request.POST.get("project_name") or m.project_name or "").strip()
        m.location     = (request.POST.get("location") or m.location or "").strip()
        # store select in building_type for now
        m.building_type = (request.POST.get("project_type") or m.building_type or "").strip()
        m.save()

        # keep active in session
        request.session["metrics_id"] = m.id
        ids = set(request.session.get("my_project_ids", []))
        ids.add(m.id)
        request.session["my_project_ids"] = list(ids)
        request.session.modified = True

        # If you have a detail view, redirect there; otherwise back to projects
        return redirect("projects")

    # GET: reuse the create form, prefilled
    return render(request, "create_project.html", {"m": m, "is_edit": True})


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
    Includes current project's metrics (if metrics_id in session).
    """
    ui_key = (request.GET.get("cls") or "").strip().lower()

    # Get metrics for current project from session
    metrics = {"gifa_m2": 0, "building_footprint_m2": 0}
    metrics_id = request.session.get("metrics_id")
    if metrics_id:
        try:
            metric_obj = Metrics.objects.filter(id=metrics_id).first()
            if metric_obj:
                metrics["gifa_m2"] = float(metric_obj.gifa_m2 or 0)
                metrics["building_footprint_m2"] = float(metric_obj.building_footprint_m2 or 0)
        except Exception:
            logger.exception("Error fetching metrics for metrics_id=%s", metrics_id)

    # Fetch interventions (dynamic SQL to handle reserved column "class")
    try:
        with connection.cursor() as cur:
            desc = connection.introspection.get_table_description(cur, "Interventions")
            colnames = [getattr(c, "name", getattr(c, "column_name", "")) for c in desc]

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
                    "cost_level": float(obj.get("cost_level") or 0),
                    "intervention_rating": float(obj.get("intervention_rating") or 0),
                    "gifa_m2": metrics.get("gifa_m2", 0),
                    "building_footprint_m2": metrics.get("building_footprint_m2", 0),
                })
    except Exception:
        logger.exception("Error fetching interventions from DB")
        items = []

    return JsonResponse({"items": items})



# =========================
# Save Metrics
# =========================

@require_POST
@login_required(login_url='login')
def save_metrics(request: HttpRequest) -> JsonResponse:
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return HttpResponseBadRequest("Invalid JSON")

    metrics_id = payload.get("metrics_id") or request.session.get("metrics_id")
    m = Metrics.objects.filter(id=metrics_id).first() if metrics_id else None
    if not m:
        m = Metrics(user=_resolve_app_user(request))

    numeric_fields = [
        "roof_area_m2", "roof_percent_gifa", "basement_size_m2", "basement_percent_gifa",
        "num_apartments", "num_keys", "num_wcs", "gifa_m2", "external_wall_area_m2",
        "external_openings_m2", "building_footprint_m2", "estimated_auto_budget_aud"
    ]
    for field in numeric_fields:
        if hasattr(m, field):
            setattr(m, field, _to_dec(payload.get(field)))

    if hasattr(m, "building_type"):
        m.building_type = payload.get("building_type") or getattr(m, "building_type", None)
    if hasattr(m, "basement_present"):
        m.basement_present = bool(payload.get("basement_present"))

    if not m.user:
        m.user = _resolve_app_user(request)

    m.save()
    request.session["metrics_id"] = m.id
    return JsonResponse({"ok": True, "metrics_id": m.id})


# =========================
# Carbon / Calculator Views
# =========================

@login_required(login_url='login')
def carbon_view(request):
    interventions = Interventions.objects.all()
    interventions_dict = {}

    CLASS_ALIASES_REVERSE = {}
    for key, aliases in CLASS_ALIASES.items():
        for a in aliases:
            CLASS_ALIASES_REVERSE[a.lower()] = key

    for i in interventions:
        db_theme = (i.theme or "other").lower()
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

    return render(request, "carbon.html", {
        "interventions_json": json.dumps(interventions_dict),
        "classes": classes,
    })


@login_required(login_url='login')
def get_intervention_effects(request):
    source_name = request.GET.get('source')
    if not source_name:
        return JsonResponse({'error': 'No source provided'}, status=400)

    effects = InterventionEffects.objects.filter(source_intervention_name=source_name)
    data = []

    for e in effects:
        target = Interventions.objects.filter(name=e.target_intervention_name).first()
        if not target:
            continue

        base_rating = float(target.intervention_rating or 0)
        max_effect_percent = 0.2  # ±20% max
        if e.effect_value is not None:
            effect_factor = float(e.effect_value) / 10 * max_effect_percent
            adjusted_rating = base_rating * (1 + effect_factor)
        else:
            adjusted_rating = base_rating

        data.append({
            'target': e.target_intervention_name,
            'effect': round(adjusted_rating, 2),
            'note': e.note
        })

    return JsonResponse({'effects': data})


@login_required(login_url='login')
def calculator(request: HttpRequest):
    if request.method == "GET":
        class_targets = list(ClassTargets.objects.values("class_name", "target_rating"))
        return render(request, "calculator.html", {"class_targets": class_targets})
    return _process_calculator_post(request)


def intervention_effects(metric, interventions, selected_ids: Optional[List[int]] = None):
    grouped_interventions = {}
    max_stage = 0

    # Determine max stage among selected interventions
    if selected_ids:
        for i in interventions:
            if i.id in selected_ids:
                stage_val = getattr(i, "stage", 0) or 0
                max_stage = max(max_stage, int(stage_val))

    for i in interventions:
        # Stage filter: skip interventions below max_stage if selection exists
        stage_val = getattr(i, "stage", 0) or 0
        if selected_ids and stage_val < max_stage:
            continue

        # Dependency check: skip if metric thresholds not met
        include = True
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

        # Base rating logic (same as broken version)
        adjusted_rating = float(i.intervention_rating or 0)
        if selected_ids and i.id in selected_ids:
            adjusted_rating *= 1.1  # +10% rating for selected interventions

        cls = i.theme or "Other"
        grouped_interventions.setdefault(cls, []).append({
            "id": str(i.id),
            "name": i.name or f"Intervention #{i.id}",
            "cost_level": float(i.cost_level or 0),
            "intervention_rating": round(adjusted_rating, 2),
            "description": i.description or "No description available",
            "stage": stage_val,
            "class_name": getattr(i, "class_name", ""),
            "theme": cls
        })

    return grouped_interventions


def _process_calculator_post(request: HttpRequest) -> HttpResponse:
    app_user = _resolve_app_user(request)
    if not app_user:
        if not getattr(request, "user", None) or not getattr(request.user, "is_authenticated", False):
            return JsonResponse({"error": "Must be authenticated to run calculator."}, status=401)
        dj_user = request.user
        username = getattr(dj_user, "username", None) or f"user_{dj_user.id}"
        email = getattr(dj_user, "email", "") or ""
        app_user, _ = AppUser.objects.get_or_create(username=username, defaults={"email": email})

    metric = Metrics.objects.filter(user=app_user).order_by("-created_at").first()
    if not metric:
        metric = Metrics.objects.create(user=app_user)

    # read selected ids from form/json
    selected_ids = []
    try:
        selected_ids = request.POST.getlist("selected_ids") or []
    except Exception:
        pass
    if not selected_ids:
        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
            selected_ids = payload.get("selected_ids") or []
        except Exception:
            selected_ids = []
    selected_ids = [int(x) for x in selected_ids if str(x).strip().isdigit()]

    interventions_qs = list(Interventions.objects.all())
    if selected_ids:
        max_stage = max([getattr(i, "stage", 0) or 0 for i in interventions_qs if i.id in selected_ids])
        interventions_qs = [i for i in interventions_qs if (getattr(i, "stage", 0) or 0) >= max_stage]

    grouped = intervention_effects(metric, interventions_qs, selected_ids)

    return render(request, "calculator_results.html", {
        "interventions": grouped,
        "interventions_json": json.dumps(grouped),
        "classes": [
            {"key": "carbon", "label": "Carbon", "target": 80},
            {"key": "health", "label": "Health & Wellbeing", "target": 60},
            {"key": "water", "label": "Water Use", "target": 30},
            {"key": "circular", "label": "Circular Economy", "target": 40},
            {"key": "resilience", "label": "Resilience", "target": 60},
            {"key": "value", "label": "Value & Cost", "target": 10},
            {"key": "biodiversity", "label": "Biodiversity", "target": 20},
        ],
        "cap_high": 300000,
    })


# =========================
# Project List / Detail
# =========================

@login_required(login_url='login')
def projects_view(request: HttpRequest):
    """
    Show ALL projects in the Metrics table.
    Use the search box to filter by name / type / location.
    """
    q = (request.GET.get("q") or "").strip()

    qs = Metrics.objects.all().order_by("-updated_at", "-created_at")

    if q:
        qs = qs.filter(
            Q(project_name__icontains=q) |
            Q(building_type__icontains=q) |
            Q(location__icontains=q)
        )

    return render(request, "projects.html", {"projects": qs, "query": q})

# app1/views.py
from django.contrib import messages

@login_required(login_url='login')
def project_detail_view(request, pk: int):
    p = Metrics.objects.filter(id=pk).first()
    if not p:
        return redirect("projects")

    session_ids = set(request.session.get("my_project_ids", []))
    owner_id = getattr(_resolve_app_user(request), "id", None)
    is_owner = (p.user_id == owner_id)
    if not is_owner and pk not in session_ids:
        return redirect("projects")

    if request.method == "POST":
        # strings
        p.project_name  = (request.POST.get("project_name")  or p.project_name  or "").strip()
        p.location      = (request.POST.get("location")      or p.location      or "").strip()
        p.building_type = (request.POST.get("building_type") or p.building_type or "").strip()

        # decimals
        for f in [
            "gifa_m2","external_wall_area_m2","external_openings_m2",
            "building_footprint_m2","roof_area_m2","roof_percent_gifa",
            "basement_size_m2","basement_percent_gifa","estimated_auto_budget_aud",
        ]:
            if hasattr(p, f):
                setattr(p, f, _to_dec(request.POST.get(f)))

        # ints + bool
        p.num_apartments = _to_int(request.POST.get("num_apartments"))
        p.num_keys       = _to_int(request.POST.get("num_keys"))
        p.num_wcs        = _to_int(request.POST.get("num_wcs"))
        p.basement_present = bool(request.POST.get("basement_present"))

        p.save()

        request.session["metrics_id"] = p.id
        request.session.modified = True

        # if user clicked the hidden fast-path button (optional)
        if request.POST.get("next") == "interventions":
            return redirect("carbon")

        # normal save → reload in edit mode with saved flag
        return redirect(f"{reverse('project_detail', args=[p.id])}?edit=1&saved=1")

    # GET
    can_edit = request.GET.get("edit") == "1"
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
            if "theme" in request.POST:
                new_theme = request.POST.get("theme", "light")
                request.session["theme"] = new_theme
                request.session.modified = True
                messages.success(request, f"Theme changed to {new_theme} mode!")

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
        except Exception:
            messages.error(request, "Unexpected error occurred. Please try again later.")
            logger.exception("Settings update failed")

        return redirect("settings")

    return render(request, "settings.html", {"user": user, "current_theme": current_theme})


@login_required(login_url='login')
def home(request):
    return render(request, 'home.html')


@login_required(login_url='login')
def calculator_results(request):
    cls = request.GET.get('cls', 'carbon')
    interventions_qs = Interventions.objects.filter(theme=cls).order_by('-intervention_rating', 'cost_level')

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
def dashboard_view(request: HttpRequest):
    """
    Dashboard overview — shows recent projects and key stats.
    """
    from app1.models import Metrics

    # Fetch the 3 most recently updated or created projects
    latest_projects = Metrics.objects.order_by("-updated_at", "-created_at")[:3]

    # Optional: count projects, calculate fake stats if needed
    total_projects = Metrics.objects.count()
    total_co2 = 2032  # Replace with a calculation later if available
    open_actions = 18
    avg_reduction = 23

    return render(request, "dashboard.html", {
        "latest_projects": latest_projects,
        "total_projects": total_projects,
        "total_co2": total_co2,
        "open_actions": open_actions,
        "avg_reduction": avg_reduction,
    })

@login_required(login_url='login')
def carbon_2_view(request):
    return render(request, 'carbon_2.html')
