import json
import logging
from decimal import Decimal, InvalidOperation
from typing import Optional, Any, Dict
from .models import MetricsSelection
from django.db import connection
from django.db.models import Q
from django.http import JsonResponse, HttpRequest, HttpResponse, HttpResponseBadRequest
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.timezone import now
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import login, logout, authenticate, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import ensure_csrf_cookie
from django.contrib.auth.models import User

from .models import Metrics, ClassTargets, Interventions, InterventionDependencies, User as AppUser
from django.http import JsonResponse

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

@require_POST

def save_selection(request):
    """
    JSON POST {selected:[intervention_ids], metrics_id?}
    Saves selected interventions for the current Metrics row, then returns ok.
    """
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return HttpResponseBadRequest("Invalid JSON")

    metrics_id = payload.get("metrics_id") or request.session.get("metrics_id")
    if not metrics_id:
        return HttpResponseBadRequest("Missing metrics_id")

    m = Metrics.objects.filter(id=metrics_id).first()
    if not m:
        return HttpResponseBadRequest("Metrics row not found")

    # normalize incoming ids to ints
    incoming_ids = []
    for x in (payload.get("selected") or []):
        try:
            incoming_ids.append(int(x))
        except Exception:
            pass

    # clear & re-create (simple and robust)
    MetricsSelection.objects.filter(metrics=m).delete()
    if incoming_ids:
        ivs = Interventions.objects.filter(id__in=incoming_ids)
        MetricsSelection.objects.bulk_create([
            MetricsSelection(metrics=m, intervention=iv) for iv in ivs
        ])

    return JsonResponse({"ok": True, "count": len(incoming_ids)})



def report_view(request):
    """
    GET /report/ — human-readable HTML summary and a 'Download PDF' link.
    """
    metrics_id = request.session.get("metrics_id")
    m = Metrics.objects.filter(id=metrics_id).first()

    # Pull selected interventions (join for fields you want to show)
    selected = (
        Interventions.objects
        .filter(metricsselection__metrics=m)
        .values("id", "name", "theme", "description", "cost_level", "intervention_rating")
        .order_by("theme", "name")
    )

    context = {
        "metrics": m,
        "selected": selected,
        "generated_at": now(),
    }
    return render(request, "report.html", context)



def report_pdf(request):
    """
    GET /report/pdf/ — return a PDF of the same report.
    Requires WeasyPrint: pip install weasyprint
    """
    metrics_id = request.session.get("metrics_id")
    m = Metrics.objects.filter(id=metrics_id).first()

    selected = (
        Interventions.objects
        .filter(metricsselection__metrics=m)
        .values("id", "name", "theme", "description", "cost_level", "intervention_rating")
        .order_by("theme", "name")
    )

    context = {
        "metrics": m,
        "selected": selected,
        "generated_at": now(),
        "as_pdf": True,  # minor template tweaks if you want
    }

    html = render_to_string("report.html", context, request=request)

    try:
        from weasyprint import HTML
    except Exception:
        return HttpResponseBadRequest("WeasyPrint not installed. Run: pip install weasyprint")

    pdf = HTML(string=html, base_url=request.build_absolute_uri("/")).write_pdf()
    resp = HttpResponse(pdf, content_type="application/pdf")
    filename = f"project-report-{metrics_id}.pdf"
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


@require_GET
def interventions_api(request):
    ui_key = (request.GET.get("cls") or "").strip().lower()
    metrics_id = request.GET.get("mid")
    mrow = Metrics.objects.filter(id=metrics_id).first() if metrics_id else None

    qs = Interventions.objects.all()

    # class filter (unchanged) ...
    if ui_key:
        terms = CLASS_ALIASES.get(ui_key, [ui_key])
        q = Q()
        for t in terms:
            q |= Q(class_name__icontains=t)
        qs = qs.filter(q)

    qs = qs.order_by("theme", "name")

    items = []
    total = qs.count()
    matched = 0

    for iv in qs:
        rules = list(getattr(iv, "rules", []).all())
        # If a metrics row is provided, REQUIRE the rules to pass.
        if mrow:
            # If there are no rules, treat as "always allowed" OR "exclude" — choose one.
            # If you want "basement" interventions to be excluded unless rules say otherwise,
            # keep some naming guard (optional quick safety):
            if rules:
                if not matches_intervention(mrow, rules):
                    continue
            else:
                # Optional: a light naming filter to avoid obvious mismatches when there are no rules yet.
                if (not mrow.basement_present) and ('basement' in (iv.name or '').lower()):
                    continue

        matched += 1
        items.append({
            "id": iv.id,
            "name": iv.name or f"Intervention #{iv.id}",
            "theme": iv.theme or "",
            "description": iv.description or "",
            "cost_level": iv.cost_level or 0,
            "intervention_rating": iv.intervention_rating or 0,
            "cost_range": getattr(iv, "cost_range", "") or "",
            "class_name": iv.class_name or "",
        })

    return JsonResponse({
        "items": items,
        "debug": {
            "total_before_filter": total,
            "metrics_id": metrics_id,
            "returned_after_filter": matched,
            "class_key": ui_key,
        }
    })@require_GET
def interventions_api(request):
    """
    GET /api/interventions/?cls=<class_key>&mid=<metrics_id>
    Returns interventions filtered by:
      - optional class
      - metrics-aware rules (matches_intervention) if present
      - fallback heuristics when rules are missing
    """
    ui_key = (request.GET.get("cls") or "").strip().lower()
    metrics_id = request.GET.get("mid") or request.session.get("metrics_id")

    mrow = Metrics.objects.filter(id=metrics_id).first() if metrics_id else None

    qs = Interventions.objects.all()

    # Class filter (lenient aliases)
    if ui_key:
        terms = CLASS_ALIASES.get(ui_key, [ui_key])
        q = Q()
        for t in terms:
            q |= Q(class_name__icontains=t)
        qs = qs.filter(q)

    qs = qs.order_by("theme", "name")

    # ---- Heuristic filters when no rule rows exist ----
    def _zero(x):  # treat None or <=0 as zero
        try:
            return (x is None) or (float(x) <= 0)
        except Exception:
            return True

    # quick keyword bags
    BASEMENT_WORDS = ("basement", "substructure", "foundation", "footing")
    ROOF_WORDS     = ("roof", "rooftop", "green roof", "cool roof")
    WALL_WORDS     = ("external wall", "façade", "facade", "cladding", "external wall insulation", "ewi")
    OPENING_WORDS  = ("window", "glazing", "fenestration", "external opening", "door")
    FOOTPRINT_WORDS= ("footprint", "ground floor", "slab on grade")

    def needs_basement(text):
        t = (text or "").lower()
        return any(w in t for w in BASEMENT_WORDS)

    def needs_roof(text):
        t = (text or "").lower()
        return any(w in t for w in ROOF_WORDS)

    def needs_wall(text):
        t = (text or "").lower()
        return any(w in t for w in WALL_WORDS)

    def needs_openings(text):
        t = (text or "").lower()
        return any(w in t for w in OPENING_WORDS)

    def needs_footprint(text):
        t = (text or "").lower()
        return any(w in t for w in FOOTPRINT_WORDS)

    def suppressed_by_metrics(iv: "Interventions", m: "Metrics") -> bool:
        """
        Return True when this intervention should be hidden for the given metrics row.
        Use this only when there are NO rule rows on the intervention.
        """
        title = f"{iv.name or ''} {iv.description or ''}"

        # Basement logic
        if needs_basement(title):
            if not bool(getattr(m, "basement_present", False)):
                return True
            # if present but size is zero, also hide size-dependent basement items
            if _zero(getattr(m, "basement_size_m2", None)):
                return True

        # Roof logic
        if needs_roof(title):
            roof_area = getattr(m, "roof_area_m2", None)
            roof_pct  = getattr(m, "roof_percent_gifa", None)
            if _zero(roof_area) and _zero(roof_pct):
                return True

        # External wall / façade logic
        if needs_wall(title):
            if _zero(getattr(m, "external_wall_area_m2", None)):
                return True

        # Openings / windows
        if needs_openings(title):
            if _zero(getattr(m, "external_openings_m2", None)):
                return True

        # Footprint-dependent
        if needs_footprint(title):
            if _zero(getattr(m, "building_footprint_m2", None)):
                return True

        # If everything is zero including GIFA, you might want to hide
        # interventions that clearly require any building area at all.
        # (Optional – uncomment if desired)
        # gifa = getattr(m, "gifa_m2", None)
        # if _zero(gifa):
        #     return True

        return False

    total = qs.count()
    returned = 0
    items = []

    for iv in qs:
        # Collect rule rows if present
        try:
            rules = list(getattr(iv, "rules", []).all())
        except Exception:
            rules = []

        # Apply rules first when we have both mrow and rules
        if mrow and rules:
            try:
                if not matches_intervention(mrow, rules):
                    continue  # filtered out by rule engine
            except Exception:
                # If rule evaluation fails, fall back to heuristics below
                rules = []

        # If there are no rules (or rule eval failed), apply heuristics
        if mrow and not rules:
            if suppressed_by_metrics(iv, mrow):
                continue

        returned += 1
        items.append({
            "id": iv.id,
            "name": iv.name or f"Intervention #{iv.id}",
            "theme": iv.theme or "",
            "description": iv.description or "",
            "cost_level": iv.cost_level or 0,
            "intervention_rating": iv.intervention_rating or 0,
            "cost_range": getattr(iv, "cost_range", "") or "",
        })

    return JsonResponse({
        "items": items,
        "debug": {
            "metrics_id": metrics_id,
            "class_key": ui_key,
            "total_before_filter": total,
            "returned_after_filter": returned,
        }
    })


# =========================
# Save Metrics
# =========================

@require_POST
@login_required(login_url='login')
def save_metrics(request: HttpRequest) -> JsonResponse:
    try:
        payload: Dict[str, Any] = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return HttpResponseBadRequest("Invalid JSON")

    metrics_id = payload.get("metrics_id") or request.session.get("metrics_id")
    m = Metrics.objects.filter(id=metrics_id).first() if metrics_id else None
    if not m:
        m = Metrics(user=_resolve_app_user(request))

    # Dynamically update numeric fields if they exist
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


@login_required(login_url='login')
def calculator(request: HttpRequest):
    if request.method == "GET":
        class_targets = list(ClassTargets.objects.values("class_name", "target_rating"))
        return render(request, "calculator.html", {"class_targets": class_targets})

    # POST now renders the results page
    return _process_calculator_post(request)




def _process_calculator_post(request: HttpRequest) -> HttpResponse:
    logger.debug("Calculator POST triggered")

    # Load latest metrics for this user
    metric = Metrics.objects.filter(user=request.user).order_by("-created_at").first()
    if not metric:
        logger.warning("No metrics found for user %s", request.user)
        return render(request, "calculator_results.html", {"interventions": []})

    interventions = Interventions.objects.all()
    final_interventions = []

    for intervention in interventions:
        deps = InterventionDependencies.objects.filter(intervention_id=intervention.id)
        include_intervention = True

        for dep in deps:
            metric_value_raw = getattr(metric, dep.metric_name, None)
            if metric_value_raw is None:
                # Skip this dependency if the metric is not provided
                continue

            try:
                metric_value = Decimal(metric_value_raw)
            except Exception:
                logger.warning("Invalid metric value for %s: %s", dep.metric_name, metric_value_raw)
                continue

            # Only exclude if metric violates min/max
            if (dep.min_value is not None and metric_value < dep.min_value) or \
               (dep.max_value is not None and metric_value > dep.max_value):
                include_intervention = False
                break

        if include_intervention:
            final_interventions.append(intervention)

    # Group interventions by theme for template
    grouped_interventions = {}
    for i in final_interventions:
        grouped_interventions.setdefault(i.theme or "Other", []).append(i)

    return render(request, "calculator_results.html", {
        "interventions": grouped_interventions,
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


