# app1/views.py
import json
import logging
import re
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Optional, Any, List

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import connection
from django.db.models import Q, Avg, Count
from django.db.models.functions import Coalesce, ExtractYear
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseBadRequest,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_GET, require_POST

from .models import (
    ClassTargets,
    InterventionDependencies,
    InterventionEffects,
    Interventions,
    Metrics,
    User as AppUser,
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


def _to_int(value: Any) -> Optional[int]:
    if value in (None, "", "null"):
        return None
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return None


NUM_RE = re.compile(r"[^0-9\.\-]")  # keep digits, dot, minus only

def _to_dec(value: Any, *, default: Optional[Decimal] = None) -> Optional[Decimal]:
    """
    Safely convert many user inputs to Decimal.
    - Removes commas, units, %, spaces (keeps only 0-9 . -)
    - Treats '', None, 'null', 'nan', 'inf' as invalid -> returns default
    """
    if value in (None, "", "null"):
        return default
    s = str(value).strip()
    s_lower = s.lower()
    if s_lower in ("nan", "+nan", "-nan", "inf", "+inf", "-inf"):
        return default
    cleaned = NUM_RE.sub("", s)
    if cleaned in ("", "-", ".", "-.", ".-"):
        return default
    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError, TypeError):
        return default


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
        project_name = (request.POST.get("project_name") or "").strip()
        project_location = (request.POST.get("location") or request.POST.get("project_location") or "").strip()
        project_type = (request.POST.get("project_type") or "").strip()

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
    GET -> renders the same form as create, prefilled
    POST -> saves and redirects to Projects (or wherever you like)
    """
    m = get_object_or_404(Metrics, pk=pk)

    if request.method == "POST":
        m.project_name = (request.POST.get("project_name") or m.project_name or "").strip()
        m.location = (request.POST.get("location") or m.location or "").strip()
        m.building_type = (request.POST.get("project_type") or m.building_type or "").strip()
        m.save()

        # keep active in session for calculator/interventions
        request.session["metrics_id"] = m.id
        request.session.modified = True

        return redirect("projects")

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
                items.append(
                    {
                        "id": obj.get("id"),
                        "name": obj.get("name") or f"Intervention #{obj.get('id')}",
                        "theme": obj.get("theme") or "",
                        "description": obj.get("description") or "",
                        "cost_level": float(obj.get("cost_level") or 0),
                        "intervention_rating": float(obj.get("intervention_rating") or 0),
                        "gifa_m2": metrics.get("gifa_m2", 0),
                        "building_footprint_m2": metrics.get("building_footprint_m2", 0),
                    }
                )
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
    """
    Save building metrics for the current project.
    Stores the manually entered Total Budget (global_budget) into total_budget_aud.
    """
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return HttpResponseBadRequest("Invalid JSON")

    # Find or create Metrics instance
    metrics_id = payload.get("metrics_id") or request.session.get("metrics_id")
    m = Metrics.objects.filter(id=metrics_id).first() if metrics_id else None
    if not m:
        m = Metrics(user=_resolve_app_user(request))

    # --- Decimal fields ---
    decimal_fields = [
        "gifa_m2",
        "external_wall_area_m2",
        "external_openings_m2",
        "building_footprint_m2",
        "roof_area_m2",
        "roof_percent_gifa",
        "basement_size_m2",
        "basement_percent_gifa",
    ]
    for field in decimal_fields:
        if hasattr(m, field):
            # Use 0 default so non-null DecimalFields won't explode
            setattr(m, field, _to_dec(payload.get(field), default=Decimal("0")))

    # --- Integer fields ---
    if hasattr(m, "num_apartments"):
        m.num_apartments = _to_int(payload.get("num_apartments"))
    if hasattr(m, "num_keys"):
        m.num_keys = _to_int(payload.get("num_keys"))
    if hasattr(m, "num_wcs"):
        m.num_wcs = _to_int(payload.get("num_wcs"))

    # --- Boolean & string fields ---
    if hasattr(m, "basement_present"):
        bp = payload.get("basement_present")
        m.basement_present = str(bp).lower() in ("1", "true", "yes", "on")
    if hasattr(m, "building_type"):
        m.building_type = payload.get("building_type") or getattr(m, "building_type", None)

    # --- Total budget logic (default 0 for invalid/missing) ---
    if hasattr(m, "total_budget_aud"):
        global_budget = payload.get("global_budget")
        m.total_budget_aud = _to_dec(global_budget, default=Decimal("0"))

    # --- Ensure user ownership ---
    if not m.user:
        m.user = _resolve_app_user(request)

    # Save with diagnostics (to avoid 500s)
    try:
        m.save()
    except Exception as e:
        logger.exception("Failed to save Metrics")
        return JsonResponse({"ok": False, "error": f"{e.__class__.__name__}: {e}"}, status=400)

    # Persist session
    request.session["metrics_id"] = m.id
    request.session.modified = True

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

        interventions_dict.setdefault(cls_key, []).append(
            {
                "id": i.id,
                "name": i.name or f"Intervention #{i.id}",
                "cost": float(i.cost_level or 0),
                "rating": float(i.intervention_rating or 0),
                "badges": [i.theme.capitalize()] if i.theme else [],
            }
        )

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

    return render(
        request,
        "carbon.html",
        {"interventions_json": json.dumps(interventions_dict), "classes": classes},
    )


@login_required(login_url='login')
def get_intervention_effects(request):
    source_name = request.GET.get("source")
    if not source_name:
        return JsonResponse({"error": "No source provided"}, status=400)

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

        data.append(
            {
                "target": e.target_intervention_name,
                "effect": round(adjusted_rating, 2),
                "note": e.note,
            }
        )

    return JsonResponse({"effects": data})


@login_required(login_url='login')
def calculator(request: HttpRequest):
    if request.method == "GET":
        class_targets = list(ClassTargets.objects.values("class_name", "target_rating"))
        return render(request, "calculator.html", {"class_targets": class_targets})
    return _process_calculator_post(request)


def intervention_effects(
    metric, interventions, selected_ids: Optional[List[int]] = None
):
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
            if (dep.min_value is not None and val < dep.min_value) or (
                dep.max_value is not None and val > dep.max_value
            ):
                include = False
                break
        if not include:
            continue

        # Base rating logic
        adjusted_rating = float(i.intervention_rating or 0)
        if selected_ids and i.id in selected_ids:
            adjusted_rating *= 1.1  # +10% rating for selected interventions

        cls = i.theme or "Other"
        grouped_interventions.setdefault(cls, []).append(
            {
                "id": str(i.id),
                "name": i.name or f"Intervention #{i.id}",
                "cost_level": float(i.cost_level or 0),
                "intervention_rating": round(adjusted_rating, 2),
                "description": i.description or "No description available",
                "stage": stage_val,
                "class_name": getattr(i, "class_name", ""),
                "theme": cls,
            }
        )

    return grouped_interventions


def _get_current_metric(request) -> Metrics:
    """
    Resolve which Metrics row the calculator should use.
    Priority:
      1) metrics_id passed in POST/GET
      2) metrics_id stored in session
      3) latest project for this AppUser (fallback)
    """
    app_user = _resolve_app_user(request)
    metrics_id = (
        request.POST.get("metrics_id")
        or request.GET.get("metrics_id")
        or request.session.get("metrics_id")
    )

    m = Metrics.objects.filter(id=metrics_id).first() if metrics_id else None
    if not m and app_user:
        m = (
            Metrics.objects.filter(user=app_user)
            .order_by("-updated_at", "-created_at")
            .first()
        )
    if not m:
        m = Metrics.objects.create(user=app_user if app_user else None)

    request.session["metrics_id"] = m.id  # keep everyone in sync
    request.session.modified = True
    return m


def _process_calculator_post(request: HttpRequest) -> HttpResponse:
    # Use the current/edited project instead of "latest for this user"
    metric = _get_current_metric(request)

    # read selected ids from form/json
    try:
        selected_ids = request.POST.getlist("selected_ids") or []
    except Exception:
        selected_ids = []
    if not selected_ids:
        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
            selected_ids = payload.get("selected_ids") or []
        except Exception:
            selected_ids = []
    selected_ids = [int(x) for x in selected_ids if str(x).strip().isdigit()]

    interventions_qs = list(Interventions.objects.all())
    if selected_ids:
        max_stage = max(
            [
                getattr(i, "stage", 0) or 0
                for i in interventions_qs
                if i.id in selected_ids
            ]
        )
        interventions_qs = [
            i for i in interventions_qs if (getattr(i, "stage", 0) or 0) >= max_stage
        ]

    grouped = intervention_effects(metric, interventions_qs, selected_ids)

    return render(
        request,
        "calculator_results.html",
        {
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
        },
    )


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
            Q(project_name__icontains=q)
            | Q(building_type__icontains=q)
            | Q(location__icontains=q)
        )

    return render(request, "projects.html", {"projects": qs, "query": q})


@login_required(login_url='login')
def project_detail_view(request, pk: int):
    """
    View or edit a project's full details. Anyone logged in can edit.
    Use ?edit=1 to toggle editable mode (GET). POST saves changes.
    """
    p = get_object_or_404(Metrics, id=pk)

    if request.method == "POST":
        # strings
        p.project_name = (request.POST.get("project_name") or p.project_name or "").strip()
        p.location = (request.POST.get("location") or p.location or "").strip()
        p.building_type = (request.POST.get("building_type") or p.building_type or "").strip()

        # decimals
        for f in [
            "gifa_m2",
            "external_wall_area_m2",
            "external_openings_m2",
            "building_footprint_m2",
            "roof_area_m2",
            "roof_percent_gifa",
            "basement_size_m2",
            "basement_percent_gifa",
            "estimated_auto_budget_aud",
        ]:
            if hasattr(p, f):
                setattr(p, f, _to_dec(request.POST.get(f), default=Decimal("0")))

        # ints + bool
        p.num_apartments = _to_int(request.POST.get("num_apartments"))
        p.num_keys = _to_int(request.POST.get("num_keys"))
        p.num_wcs = _to_int(request.POST.get("num_wcs"))
        p.basement_present = bool(request.POST.get("basement_present"))

        p.save()

        # keep this project “active” for interventions page
        request.session["metrics_id"] = p.id
        request.session.modified = True

        if request.POST.get("next") == "interventions":
            return redirect("carbon")

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
        user = authenticate(
            request,
            username=request.POST.get("username"),
            password=request.POST.get("password"),
        )
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
    return render(request, "home.html")


@login_required(login_url='login')
def calculator_results(request):
    cls = request.GET.get("cls", "carbon")
    interventions_qs = Interventions.objects.filter(theme=cls).order_by(
        "-intervention_rating", "cost_level"
    )

    interventions = []
    for i in interventions_qs:
        interventions.append(
            {
                "id": str(i.id),
                "name": i.name,
                "theme": i.theme,
                "description": i.description,
                "cost_level": float(i.cost_level or 0),
                "intervention_rating": float(i.intervention_rating or 0),
                "cost_range": getattr(i, "cost_range", ""),
            }
        )

    return render(
        request,
        "calculator_results.html",
        {
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
            "cap_high": 300000,
        },
    )


@login_required(login_url='login')
def dashboard_view(request: HttpRequest):
    # --- Projects / budgets ---
    latest_projects = Metrics.objects.order_by("-updated_at", "-created_at")[:3]
    total_projects = Metrics.objects.count()

    avg_budget = (
        Metrics.objects.aggregate(avg_budget=Avg("total_budget_aud"))["avg_budget"]
        or Decimal("0")
    )

    # --- Intervention stats ---
    avg_intervention_rating = (
        Interventions.objects.aggregate(avg_rating=Avg("intervention_rating"))["avg_rating"]
        or 0
    )

    top_theme_data = (
        Interventions.objects.values("theme")
        .annotate(avg_rating=Avg("intervention_rating"))
        .order_by("-avg_rating")
        .first()
    )
    top_theme = top_theme_data["theme"] if top_theme_data else "N/A"
    top_theme_rating = round(top_theme_data["avg_rating"], 2) if top_theme_data else 0

    # --- YoY: number of projects created per year (last 6 years incl. current) ---
    now = timezone.now()
    start_year = now.year - 5

    yoy_raw = (
        Metrics.objects.annotate(y=ExtractYear("created_at"))
        .filter(y__gte=start_year, y__lte=now.year)
        .values("y")
        .annotate(n=Count("id"))
        .order_by("y")
    )

    yoy_map = {row["y"]: int(row["n"]) for row in yoy_raw}
    yoy_labels = [str(y) for y in range(start_year, now.year + 1)]
    yoy_counts = [yoy_map.get(int(lbl), 0) for lbl in yoy_labels]

    context = {
        "latest_projects": latest_projects,
        "total_projects": total_projects,
        "avg_budget": avg_budget,
        "avg_intervention_rating": avg_intervention_rating,
        "top_theme": top_theme,
        "top_theme_rating": top_theme_rating,
        "yoy_labels_json": json.dumps(yoy_labels),
        "yoy_counts_json": json.dumps(yoy_counts),
        "current_year": now.year,
    }

    return render(request, "dashboard.html", context)


@login_required(login_url='login')
def carbon_2_view(request):
    return render(request, "carbon_2.html")
