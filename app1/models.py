from django.db import models
from django.conf import settings


class ClassTargets(models.Model):
    class_name = models.CharField(max_length=100, primary_key=True)
    target_rating = models.FloatField()

    class Meta:
        db_table = 'ClassTargets'

    def __str__(self):
        return self.class_name


class Interventions(models.Model):
    id = models.AutoField(primary_key=True)
    class_name = models.CharField(max_length=100, db_column='class', null=True)
    theme = models.CharField(max_length=255, null=True)
    name = models.CharField(max_length=255, null=True)
    description = models.TextField(null=True)
    
    # Added fields
    cost_level = models.IntegerField(null=True)
    cost_range = models.CharField(max_length=50, null=True)
    intervention_rating = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = 'Interventions'

    def __str__(self):
        return f"{self.class_name} - {self.name}"

class InterventionDependencies(models.Model):
    intervention_id = models.IntegerField(primary_key=True)
    metric_name = models.CharField(max_length=255, db_column='metric_column')
    min_value = models.FloatField(null=True, blank=True)
    max_value = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "intervention_dependencies"
        unique_together = (('intervention_id', 'metric_name'),)
        managed = False  # Django won't create or alter this table



# app1/models.py
from django.db import models

class MetricRule(models.Model):
    """
    One rule record belongs to one intervention.
    All rules for an intervention must pass for it to be shown.
    """
    OP_CHOICES = [
        ('eq',  '=='),
        ('neq', '!='),
        ('gt',  '>'),
        ('gte', '>='),
        ('lt',  '<'),
        ('lte', '<='),
        ('in',  'in'),      # value is comma-separated list
        ('nin', 'not in'),
        ('true','is True'), # for booleans
        ('false','is False'),
        ('empty','is empty'),
        ('nempty','not empty'),
        ('contains', 'str contains'),   # for strings
        ('ncontains','str not contains'),
    ]

    intervention = models.ForeignKey('Interventions', on_delete=models.CASCADE, related_name='rules')
    # e.g. "basement_present", "gifa_m2", "project_type", etc.
    field_name   = models.CharField(max_length=100)
    operator     = models.CharField(max_length=12, choices=OP_CHOICES)
    value        = models.CharField(max_length=255, blank=True, null=True)  # store raw; we’ll parse as needed

    class Meta:
        indexes = [models.Index(fields=['intervention', 'field_name'])]






class User(models.Model):
    id = models.AutoField(primary_key=True)
    username = models.CharField(max_length=150, unique=True)
    email = models.EmailField(unique=True)
    password = models.CharField(max_length=128)

    class Meta:
        db_table = 'User'

    def __str__(self):
        return self.username
    
# add near your other models
class MetricsSelection(models.Model):
    metrics = models.ForeignKey('Metrics', on_delete=models.CASCADE, related_name="selections")
    intervention = models.ForeignKey('Interventions', on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "MetricsSelection"
        unique_together = ("metrics", "intervention")


# NEW
class Metrics(models.Model):
    id = models.AutoField(primary_key=True)

    # ✅ Now this accepts request.user directly
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="metrics",
    )

    # (Optional) store first-page project info in the same row
    project_id = models.IntegerField(null=True, blank=True, db_index=True)
    project_name = models.CharField(max_length=255, null=True, blank=True)
    project_type = models.CharField(max_length=64, null=True, blank=True)   # Residential / Commercial / Infrastructure
    location = models.CharField(max_length=255, null=True, blank=True)

    # High-level
    building_type = models.CharField(max_length=120, null=True, blank=True)

    # Roof
    roof_area_m2 = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    roof_percent_gifa = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)

    # Basement
    basement_present = models.BooleanField(default=False)
    basement_size_m2 = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    basement_percent_gifa = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)

    # Units
    num_apartments = models.PositiveIntegerField(null=True, blank=True)
    num_keys = models.PositiveIntegerField(null=True, blank=True)
    num_wcs = models.PositiveIntegerField(null=True, blank=True)

    # Areas
    gifa_m2 = models.DecimalField("GIFA (m²)", max_digits=14, decimal_places=2, null=True, blank=True)
    external_wall_area_m2 = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    external_openings_m2 = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    building_footprint_m2 = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)

    # Computed
    estimated_auto_budget_aud = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)

    # Housekeeping
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "Metrics"
        indexes = [
            models.Index(fields=["user"]),
            models.Index(fields=["project_id"]),
            models.Index(fields=["project_type"]),
            models.Index(fields=["created_at"]),
        ]

    @property
    def total_units(self) -> int:
        return (self.num_apartments or 0) + (self.num_keys or 0) + (self.num_wcs or 0)

    def __str__(self):
        return f"Metrics #{self.id} – {self.building_type or 'Building'}"

    def update_from_dict(self, data: dict):
        # handy when merging both pages into one row
        for k, v in (data or {}).items():
            if hasattr(self, k):
                setattr(self, k, v)