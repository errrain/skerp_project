from django.urls import path
from . import views

app_name = 'spec'

urlpatterns = [
    path('', views.spec_list, name='spec_list'),
    path('add/', views.spec_add, name='spec_add'),
    path('<int:pk>/edit/', views.spec_edit, name='spec_edit'),
    path('<int:pk>/delete/', views.spec_delete, name='spec_delete'),
]