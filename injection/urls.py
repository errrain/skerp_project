from django.urls import path
from . import views

app_name = 'injection'

urlpatterns = [
    path('', views.injection_list, name='injection_list'),
    path('create/', views.injection_create, name='injection_create'),
    path('<int:pk>/edit/', views.injection_update, name='injection_update'),
    path('<int:pk>/delete/', views.injection_delete, name='injection_delete'),
]
