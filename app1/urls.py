from django.contrib import admin
from django.urls import include, path
from django.contrib.auth import views as auth_views

urlpatterns = [
    # ... your existing paths ...
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
]


from . import views

urlpatterns = [
    path('', views.home, name='home'),  # Corrected to home page path
    path('calculator/', views.calculator, name='calculator'),
    path('calculator/results/', views.calculator_results, name='calculator_results'),
    path('django_browser_reload/', include('django_browser_reload.urls')),
    path('login/', views.login_view, name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('projects/', views.projects_view, name='projects'),
    path('projects/create/', views.create_project, name='create_project'),
    path('register/', views.register_view, name='register'),
]
