from django.contrib import admin
from django.urls import include, path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('', views.home, name='home'),  # Corrected to home page path
    path('calculator/', views.calculator, name='calculator'),
    path('calculator/results/', views.calculator_results, name='calculator_results'),
    path('django_browser_reload/', include('django_browser_reload.urls')),

    # Authentication
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('register/', views.register, name='register'),
    path('register_success/', views.register_success, name='register_success'),

    # Dashboard
    path('dashboard/', views.dashboard, name='dashboard'),

    # Projects
    path('projects/', views.projects, name='projects'),
    path('create_project/', views.create_project, name='create_project'),

    # Carbon page placeholder (add your view logic)
    path('carbon/', views.carbon_view, name='carbon'),  # <-- added to fix NoReverseMatch
    path('calculator/', views.calculator, name='calculator'),
    path('calculator_results/', views.calculator_results, name='calculator_results'),
    path('carbon/', views.carbon, name='carbon'),
    path('carbon_2/', views.carbon_2, name='carbon_2'),
    path("api/interventions/", views.interventions_api, name="interventions_api"),
    path("api/metrics/save/", views.save_metrics, name="save_metrics"),



]
