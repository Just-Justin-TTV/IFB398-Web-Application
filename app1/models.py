from django.db import models


class ClassTargets(models.Model):
    class_name = models.CharField(max_length=100, primary_key=True)  # or set any unique field as primary key
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



    class Meta:
        db_table = 'Interventions'

    def __str__(self):
        return f"{self.class_name} - {self.intervention}"



#class DetailedMatrix(models.Model):
 #   class_name = models.CharField(max_length=100, db_column='class', null=True)
 #   theme = models.CharField(max_length=255, null=True)
  #  intervention = models.CharField(max_length=255, db_column='Interventions', null=True)
 #   description = models.TextField(db_column='Intervention Description', null=True)
 #   impact_rating = models.FloatField(db_column='Impact Rating', null=True)
 #   low_cost = models.FloatField(db_column='Low Cost.1', null=True)
 ##   high_cost = models.FloatField(db_column='High Cost.1', null=True)

  #  class Meta:
  #      db_table = 'DetailedMatrix'

    def __str__(self):
        return f"{self.class_name} - {self.intervention}"
