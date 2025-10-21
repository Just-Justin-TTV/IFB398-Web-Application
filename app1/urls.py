from django.contrib import admin
from django.urls import include, path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('', views.home, name='home'),

    # Dashboard
    path('dashboard/', views.dashboard_view, name='dashboard'),
    

    # Auth
    path('login/', views.login_view, name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
    path('register/', views.register_view, name='register'),

    # Projects
    path('projects/', views.projects_view, name='projects'),
    path('projects/create/', views.create_project, name='create_project'),
    path('projects/<int:pk>/', views.project_detail_view, name='project_detail'),   # <-- add this
    path('metrics/<int:pk>/edit/', views.metrics_edit, name='metrics_edit'),

    # Calculator / Carbon
    path('calculator/', views.calculator, name='calculator'),
    path('calculator/results/', views.calculator_results, name='calculator_results'),  # <-- keep this one
    # (remove the duplicate that pointed to views.calculator)
    path('carbon/', views.carbon_view, name='carbon'),
    path('carbon-2/', views.carbon_2_view, name='carbon_2'),

    # APIs
    path('api/interventions/', views.interventions_api, name='interventions_api'),
    path('api/metrics/save/', views.save_metrics, name='save_metrics'),
    path('get_intervention_effects/', views.get_intervention_effects, name='get_intervention_effects'),
    path('projects/', views.projects_view, name='projects_view'),
    path('settings/', views.settings_view, name='settings'),
    path('settings/password/', PasswordChangeView.as_view(template_name='registration/password_change.html'), name='password_change'),  
    path('settings/password/done/', PasswordChangeDoneView.as_view(template_name='registration/password_change_done.html'), name='password_change_done'),

    # Dev
    path('django_browser_reload/', include('django_browser_reload.urls')),
]
