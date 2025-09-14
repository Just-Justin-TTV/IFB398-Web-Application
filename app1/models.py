from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model
User = get_user_model()


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

#class User(models.Model):
   # id = models.AutoField(primary_key=True)
  #  username = models.CharField(max_length=150, unique=True)
  #  email = models.EmailField(unique=True)
  #  password = models.CharField(max_length=128)



  #  class Meta:
  #      db_table = 'User'

  #  def __str__(self):
  #      return f"{self.class_name} - {self.intervention}"



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

#    def __str__(self):
  #      return f"{self.class_name} - {self.intervention}"
    

# settings page
class UserProfile(models.Model):
    THEME_CHOICES = [
        ('light', 'Light'),
        ('dark', 'Dark'),
        ('high-contrast', 'High Contrast'),  
    ]

    TEXT_SIZE_CHOICES = [
        ('normal', 'Normal'),
        ('large', 'Large'),
        ('x-large', 'Extra Large'), 
    ]
    
    user = models.OneToOneField(User, on_delete=models.CASCADE)  # This uses the correct User
    theme = models.CharField(max_length=15, choices=THEME_CHOICES, default='light')
    text_size = models.CharField(max_length=10, choices=TEXT_SIZE_CHOICES, default='normal')

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)

@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    if hasattr(instance, 'userprofile'):
        instance.userprofile.save()