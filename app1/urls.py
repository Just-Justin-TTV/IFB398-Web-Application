from django.contrib import admin 
from django.urls import include, path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    # Home page
    path('', views.home, name='home'),

    # Dashboard page
    path('dashboard/', views.dashboard_view, name='dashboard'),
    
    # Authentication URLs
    path('login/', views.login_view, name='login'),  # Custom login view
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),  # Logout and redirect to login
    path('register/', views.register_view, name='register'),  # User registration page

    # Project management URLs
    path('projects/', views.projects_view, name='projects'),  # List of projects
    path('projects/create/', views.create_project, name='create_project'),  # Create a new project
    path('projects/<int:pk>/', views.project_detail_view, name='project_detail'),  # Project detail page
    path('metrics/<int:pk>/edit/', views.metrics_edit, name='metrics_edit'),  # Edit metrics for a specific project

    # Calculator / Carbon footprint URLs
    path('calculator/', views.calculator, name='calculator'),  # Calculator input page
    path('calculator/results/', views.calculator_results, name='calculator_results'),  # Display calculation results
    path('carbon/', views.carbon_view, name='carbon'),  # Carbon view page
    path('carbon-2/', views.carbon_2_view, name='carbon_2'),  # Alternative carbon view

    # API endpoints for interventions
    path("api/projects/<int:metrics_id>/interventions/", views.intervention_selection_list_api, name="intervention_selection_list_api"),  # List interventions for a project
    path("api/projects/<int:metrics_id>/interventions/save/", views.intervention_selection_save_api, name="intervention_selection_save_api"),  # Save selected interventions
    path('api/interventions/', views.interventions_api, name='interventions_api'),  # API for retrieving interventions
    path('api/metrics/save/', views.save_metrics, name='save_metrics'),  # API for saving metrics
    path('get_intervention_effects/', views.get_intervention_effects, name='get_intervention_effects'),  # Retrieve effects of interventions

    # Additional project and settings pages
    path('projects/', views.projects_view, name='projects_view'),  # Duplicate path for projects list (optional)
    path('settings/', views.settings_view, name='settings'),  # Settings page
    path('reports/', views.reports_page, name='reports'),  # Reports overview page
    path('api/reports/generate/<int:project_id>/', views.generate_report, name='generate_report'),  # Generate report via API

    # Development utilities
    path('django_browser_reload/', include('django_browser_reload.urls')),  # Browser reload for development

    # Report generation (duplicate path for reports, allows direct access)
    path('reports/generate/<int:project_id>/', views.generate_report, name='generate_report'),
]
