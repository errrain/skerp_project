from django.urls import path
from . import views

app_name = 'master'

urlpatterns = [
    path('company/', views.company_list, name='company_list'),
    path('company/create/', views.company_create, name='company_create'),
    path('company/<int:pk>/edit/', views.company_edit, name='company_edit'),
    path('company/<int:pk>/delete/', views.company_delete, name='company_delete'),
]