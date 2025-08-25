from django.db import models

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

    class Meta:
        db_table = 'Interventions'

    def __str__(self):
        return f"{self.class_name} - {self.name}"


class User(models.Model):
    id = models.AutoField(primary_key=True)
    username = models.CharField(max_length=150, unique=True)
    email = models.EmailField(unique=True)
    password = models.CharField(max_length=128)

    class Meta:
        db_table = 'User'

    def __str__(self):
        return self.username
