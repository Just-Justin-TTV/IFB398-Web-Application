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
from .models import InterventionEffects
from typing import List, Dict

from .models import Metrics, ClassTargets, Interventions, InterventionDependencies, User as AppUser
from django.http import JsonResponse

logger = logging.getLogger(__name__)
from .models import User as AppUser

# After creating the Django User



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
        # Fetch all class targets to display on the calculator page
        class_targets = list(ClassTargets.objects.values("class_name", "target_rating"))
        return render(request, "calculator.html", {"class_targets": class_targets})

    # Handle POST (user submits selected interventions)
    return _process_calculator_post(request)


def intervention_effects(metric, interventions, selected_ids: Optional[List[int]] = None):
    """
    Adjust intervention ratings dynamically based only on selection.
    Ratings are only increased for interventions that are selected.
    """
    grouped_interventions = {}

    for i in interventions:
        include = True

        # Check dependencies for metric thresholds (keep if you still need them)
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

        # Base rating from DB
        adjusted_rating = float(i.intervention_rating or 0)

        # Apply only selection multiplier
        if selected_ids and i.id in selected_ids:
            adjusted_rating *= 1.1  # +10% rating for selection

        # Optional: round to 2 decimals
        adjusted_rating = round(adjusted_rating, 2)

        cls = i.theme or "Other"
        grouped_interventions.setdefault(cls, []).append({
            "id": str(i.id),
            "name": i.name or f"Intervention #{i.id}",
            "cost_level": float(i.cost_level or 0),
            "intervention_rating": adjusted_rating,
            "description": i.description or "No description available",
            "stage": getattr(i, "stage", ""),
            "class_name": getattr(i, "class_name", ""),
            "theme": cls
        })

    return grouped_interventions







def _process_calculator_post(request: HttpRequest) -> HttpResponse:
    """
    Internal helper to process POST requests from the calculator.
    If there's no corresponding AppUser row for the logged-in Django User,
    create one on-the-fly so downstream queries (Metrics.user) work.
    """
    import json
    from django.db import IntegrityError

    # 1) Resolve AppUser or create one if missing (Option 1)
    app_user = _resolve_app_user(request)
    if not app_user:
        # If the visitor is not authenticated, we can't create an AppUser for them.
        if not getattr(request, "user", None) or not getattr(request.user, "is_authenticated", False):
            return JsonResponse({"error": "Must be authenticated to run calculator."}, status=401)

        # Try to get_or_create an AppUser for the currently logged-in Django user.
        dj_user = request.user
        username = getattr(dj_user, "username", None) or f"user_{dj_user.id}"
        email = getattr(dj_user, "email", "") or ""

        try:
            app_user, created = AppUser.objects.get_or_create(
                username=username,
                defaults={"email": email}
            )
            if created:
                logger.info("Created AppUser on-the-fly for Django user %s (username=%s)", dj_user.id, username)
        except IntegrityError:
            # In case of a race/uniqueness issue, try a safe fallback lookup by email then username
            app_user = None
            if email:
                app_user = AppUser.objects.filter(email=email).first()
            if not app_user:
                app_user = AppUser.objects.filter(username=username).first()
            if not app_user:
                logger.exception("Failed to create/find an AppUser for Django user %s", getattr(dj_user, "id", "unknown"))
                return JsonResponse({"error": "Unable to ensure AppUser for this login."}, status=500)

    # 2) Retrieve or create a Metrics row for this AppUser
    metric = Metrics.objects.filter(user=app_user).order_by("-created_at").first()
    if not metric:
        metric = Metrics.objects.create(user=app_user)
        logger.info("Created Metrics row id=%s for AppUser id=%s", metric.id, app_user.id)

    # 3) Read selected intervention ids from POST (works for form or AJAX form-encoded)
    # Accept either form field 'selected_ids' repeated, or a comma-separated string, or JSON body.
    selected_ids = []
    # Try typical form list (e.g. request.POST.getlist)
    try:
        selected_ids = request.POST.getlist("selected_ids") or []
    except Exception:
        selected_ids = []

    # If nothing, try JSON body (some clients send JSON)
    if not selected_ids:
        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
            if isinstance(payload, dict) and "selected_ids" in payload:
                selected_ids = payload.get("selected_ids") or []
        except Exception:
            # ignore parse errors; we'll fallback to empty
            selected_ids = []

    # Normalize to ints
    try:
        selected_ids = [int(x) for x in selected_ids if str(x).strip().isdigit()]
    except Exception:
        selected_ids = []

    # 4) Query interventions and compute effects using your helper
    interventions_qs = Interventions.objects.all()
    grouped_interventions = intervention_effects(metric, interventions_qs, selected_ids)

    # 5) Render results page (adapt keys to your template)
    return render(request, "calculator_results.html", {
        "interventions": grouped_interventions,
        "interventions_json": json.dumps(grouped_interventions),
        # keep the same classes/caps used elsewhere
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


