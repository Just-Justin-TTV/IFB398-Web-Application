from django.contrib import admin
from django.urls import include, path
from . import views
from django.contrib.auth.views import PasswordChangeView, PasswordChangeDoneView  

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
    # settings page
    path('settings/', views.settings_view, name='settings'),
    path('settings/password/', PasswordChangeView.as_view(template_name='registration/password_change.html'), name='password_change'),  
    path('settings/password/done/', PasswordChangeDoneView.as_view(template_name='registration/password_change_done.html'), name='password_change_done'),
]