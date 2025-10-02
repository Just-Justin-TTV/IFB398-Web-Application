from django.contrib import admin
from django.urls import include, path
from django.contrib.auth import views as auth_views
from . import views
from django.contrib.auth.views import PasswordChangeView, PasswordChangeDoneView  

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
    path('projects/<int:pk>/', views.project_detail_view, name='project_detail'),

    path('projects/create/', views.create_project, name='create_project'),

    # Carbon page placeholder (add your view logic)
    path('carbon/', views.carbon_view, name='carbon'),  # <-- added to fix NoReverseMatch
    path('calculator/results/', views.calculator, name='calculator_results'),
    path('carbon-2/', views.carbon_2_view, name='carbon_2'),
    path('carbon_2/', views.carbon_2_view, name='carbon_2'),
    path("api/interventions/", views.interventions_api, name="interventions_api"),
    path("api/metrics/save/", views.save_metrics, name="save_metrics"),
    # app1/urls.py
    path("api/conflicts/", views.conflicts_api, name="conflicts_api"),




    # settings page
    path('settings/', views.settings_view, name='settings'),
    path('settings/password/', PasswordChangeView.as_view(template_name='registration/password_change.html'), name='password_change'),  
    path('settings/password/done/', PasswordChangeDoneView.as_view(template_name='registration/password_change_done.html'), name='password_change_done'),
]