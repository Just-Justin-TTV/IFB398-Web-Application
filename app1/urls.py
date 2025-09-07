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
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
    path('register/', views.register_view, name='register'),

    # Dashboard
    path('dashboard/', views.dashboard_view, name='dashboard'),

    # Projects
    path('projects/', views.projects_view, name='projects'),
    path('projects/create/', views.create_project, name='create_project'),

    # Carbon page placeholder (add your view logic)
    path('carbon/', views.carbon_view, name='carbon'),  # <-- added to fix NoReverseMatch
    path('calculator/results/', views.calculator, name='calculator_results'),
    path('carbon-2/', views.carbon_2_view, name='carbon_2'),
    path('carbon_2/', views.carbon_2_view, name='carbon_2'),


]
