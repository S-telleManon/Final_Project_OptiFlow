from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
from django.contrib.auth.views import PasswordChangeView
from .services.optimiser import run_optimizer

urlpatterns = [
    path('dashboard/', views.dashboard, name='dashboard'),
    path('upload/', views.upload, name='upload'),
    path('list/', views.shipment_list, name='shipment_list'),
    path('users/', views.users_list, name='users_list'),
    path('add_department/', views.add_department, name='add_department'),
    path('login/', views.login_view, name='login_view'),
    path('logout/', views.logout_view, name='logout'),
    path('password-change/', PasswordChangeView.as_view(template_name='shipments/password_change.html'), name='password_change'),
    path('users/', views.users_list, name='users_list'),
    path('users/create/', views.create_user, name='create_user'),
    path('users/edit/<int:user_id>/', views.edit_user, name='edit_user'),
    path('users/delete/<int:user_id>/', views.delete_user, name='delete_user'),
    path('schedules/', views.driver_schedule_view, name='driver_schedule'),
    path('routes/',run_optimizer, name='routes'),
    path('routes/display', views.routes_page, name='routes_diplay'),
    path('bulk-action/', views.bulk_action, name='bulk_action')
]