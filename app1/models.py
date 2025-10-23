from django.db import models 
from django.contrib.auth.models import User


class ClassTargets(models.Model):
    """
    Represents target ratings for each class.
    """
    class_name = models.CharField(max_length=100, primary_key=True)  # Class identifier
    target_rating = models.FloatField()  # Target rating for the class

    class Meta:
        db_table = 'ClassTargets'  # Specify custom table name

    def __str__(self):
        return self.class_name  # Display class name in admin or console


class Interventions(models.Model):
    """
    Represents interventions applicable to classes, including cost and rating.
    """
    id = models.AutoField(primary_key=True)
    class_name = models.CharField(max_length=100, db_column='class', null=True)
    theme = models.CharField(max_length=255, null=True)
    name = models.CharField(max_length=255, null=True)
    description = models.TextField(null=True)
    
    # Additional fields related to cost and effectiveness
    cost_level = models.IntegerField(null=True)  # Scale of cost (e.g., 1–5)
    cost_range = models.CharField(max_length=50, null=True)  # Human-readable cost range
    intervention_rating = models.IntegerField(null=True, blank=True)  # Optional rating for the intervention

    class Meta:
        db_table = 'Interventions'

    def __str__(self):
        return f"{self.class_name} - {self.name}"  # Display class and intervention name


class InterventionDependencies(models.Model):
    """
    Defines dependencies for interventions based on metrics.
    """
    intervention_id = models.IntegerField(primary_key=True)  # Reference to intervention
    metric_name = models.CharField(max_length=255, db_column='metric_column')  # Metric that affects intervention
    min_value = models.FloatField(null=True, blank=True)  # Minimum metric value required
    max_value = models.FloatField(null=True, blank=True)  # Maximum metric value allowed

    class Meta:
        db_table = "intervention_dependencies"
        unique_together = (('intervention_id', 'metric_name'),)  # Ensure uniqueness of combination
        managed = False  # Table is managed externally, Django will not create/alter


class AppUser(models.Model):
    """
    Custom user model storing basic authentication information.
    """
    id = models.AutoField(primary_key=True)
    username = models.CharField(max_length=150, unique=True)
    email = models.EmailField(unique=True)
    password = models.CharField(max_length=128)

    class Meta:
        db_table = 'User'

    def __str__(self):
        return self.username  # Display username


class InterventionEffects(models.Model):
    """
    Stores the effect values of one intervention on another.
    """
    source_intervention_name = models.CharField(max_length=255, db_column='source_intervention_name')
    target_intervention_name = models.CharField(max_length=255, db_column='target_intervention_name')
    effect_value = models.FloatField()  # Numeric value representing the effect
    note = models.TextField(null=True, blank=True)  # Optional notes about the effect

    class Meta:
        db_table = 'intervention_effects'

    def __str__(self):
        return f"{self.source_intervention_name} → {self.target_intervention_name} ({self.effect_value})"


class Metrics(models.Model):
    """
    Stores the values entered on the Building Metrics step.
    Includes building areas, units, and optional computed outputs.
    """
    id = models.AutoField(primary_key=True)

    # Optional user/project linkage
    user = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True, related_name="metrics")
    project_code = models.CharField(max_length=120, null=True, blank=True)  # Free-form link to a project

    # High-level building info
    building_type = models.CharField(max_length=120, null=True, blank=True)

    # Roof measurements
    roof_area_m2 = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    roof_percent_gifa = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)

    # Basement measurements
    basement_present = models.BooleanField(default=False)
    basement_size_m2 = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    basement_percent_gifa = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)

    # Unit counts
    num_apartments = models.PositiveIntegerField(null=True, blank=True)
    num_keys = models.PositiveIntegerField(null=True, blank=True)
    num_wcs = models.PositiveIntegerField(null=True, blank=True)

    # Derived areas
    gifa_m2 = models.DecimalField("GIFA (m²)", max_digits=14, decimal_places=2, null=True, blank=True)
    external_wall_area_m2 = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    external_openings_m2 = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    building_footprint_m2 = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)

    # Optional computed outputs
    total_budget_aud = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    selected_intervention_ids = models.JSONField(default=list, blank=True)  # Store selected intervention IDs

    # Additional project info
    project_name = models.CharField(max_length=255, null=True, blank=True)
    location = models.CharField(max_length=255, null=True, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "Metrics"
        indexes = [
            models.Index(fields=["building_type"]),
            models.Index(fields=["project_code"]),
            models.Index(fields=["created_at"]),
        ]

    @property
    def total_units(self) -> int:
        """
        Computes total units in the building by summing apartments, keys, and WCs.
        """
        return (self.num_apartments or 0) + (self.num_keys or 0) + (self.num_wcs or 0)

    def __str__(self):
        return f"Metrics #{self.id} – {self.building_type or 'Building'}"

    def update_from_dict(self, data: dict):
        """
        Update model fields from a dictionary. Useful for merging multiple form pages.
        """
        for k, v in (data or {}).items():
            if hasattr(self, k):
                setattr(self, k, v)


class InterventionSelection(models.Model):
    """
    Stores which interventions are selected for a given project (Metrics row).
    One row per (project, intervention) combination.
    """
    project = models.ForeignKey("Metrics", on_delete=models.CASCADE, related_name="intervention_selections")
    intervention = models.ForeignKey("Interventions", on_delete=models.CASCADE, related_name="selections")
    selected_by = models.ForeignKey('auth.User', null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "InterventionSelection"
        unique_together = ("project", "intervention")  # Ensure unique selection per project

    def __str__(self):
        return f"{self.project_id} → {self.intervention_id}"
    
class UserProfile(models.Model):
    USER_TYPES = [
        ('admin', 'Admin'),
        ('user', 'User'),
    ]

    user = models.OneToOneField('auth.User', on_delete=models.CASCADE)
    user_type = models.CharField(max_length=10, choices=USER_TYPES, default='user')

    def __str__(self):
        return f"{self.user.username} ({self.user_type})"