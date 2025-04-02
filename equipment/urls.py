# equipment/urls.py

from django.urls import path
from . import views

app_name = 'equipment'

urlpatterns = [
    path('', views.equipment_list, name='equipment_list'),
    path('add/', views.equipment_add, name='equipment_add'),
    path('<int:pk>/edit/', views.equipment_edit, name='equipment_edit'),
    path('<int:pk>/delete/', views.equipment_delete, name='equipment_delete'),

]