from django.db import models

class User(models.Model):
    id = models.AutoField(primary_key=True)
    username = models.CharField(max_length=150, unique=True)
    email = models.EmailField(unique=True)
    password = models.CharField(max_length=128)

    class Meta:
        db_table = 'User'

    def __str__(self):
        return self.username

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

class InterventionEffects(models.Model):
    source_intervention_name = models.CharField(max_length=255, db_column='source_intervention_name')
    target_intervention_name = models.CharField(max_length=255, db_column='target_intervention_name')
    effect_value = models.FloatField()
    note = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'intervention_effects'

    def __str__(self):
        return f"{self.source_intervention_name} → {self.target_intervention_name} ({self.effect_value})"

class Metrics(models.Model):
    """
    Stores the values entered on the Building Metrics step.
    Numbers use DecimalField for consistent units (m², %).
    """
    id = models.AutoField(primary_key=True)

    # Optional linkage
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="metrics")
    project_code = models.CharField(max_length=120, null=True, blank=True)  # free-form link to a project if needed

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

    # Derived areas
    gifa_m2 = models.DecimalField("GIFA (m²)", max_digits=14, decimal_places=2, null=True, blank=True)
    external_wall_area_m2 = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    external_openings_m2 = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    building_footprint_m2 = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)

    # Optional computed outputs
    estimated_auto_budget_aud = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)

    # Project info
    project_name = models.CharField(max_length=255, null=True, blank=True)
    location = models.CharField(max_length=255, null=True, blank=True)

    # Housekeeping
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
        return (self.num_apartments or 0) + (self.num_keys or 0) + (self.num_wcs or 0)

    def __str__(self):
        return f"Metrics #{self.id} – {self.building_type or 'Building'}"

    def update_from_dict(self, data: dict):
        # handy when merging both pages into one row
        for k, v in (data or {}).items():
            if hasattr(self, k):
                setattr(self, k, v)

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    theme = models.CharField(max_length=20, default='light')
    text_size = models.CharField(max_length=20, default='normal')
    
    class Meta:
        db_table = 'UserProfile'

    def __str__(self):
        return f"{self.user.username}'s Profile"