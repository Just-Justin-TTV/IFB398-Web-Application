from django.contrib import admin
from django.urls import include, path

from . import views

urlpatterns = [
    path('', views.home, name='home'),  # Corrected to home page path
    path('calculator/', views.calculator, name='calculator'),
    path('calculator/results/', views.calculator_results, name='calculator_results'),
    path('django_browser_reload/', include('django_browser_reload.urls')),
    path('login/', views.login_view, name='login'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('projects/', views.projects_view, name='projects'),
    path('projects/create/', views.create_project, name='create_project'),
    path('register/', views.register_view, name='register'),
    path('carbon/', views.carbon_view, name='carbon'),
    path("carbon/step-2/", views.carbon_step2, name="carbon_2"),
    path('create-project-step2/', views.create_project_step2, name='create_project_step2'),
]
