from django.urls import path
from . import views

app_name = 'master'

urlpatterns = [
    path('company/', views.company_list, name='company_list'),
    path('company/create/', views.company_create, name='company_create'),
    path('company/<int:pk>/edit/', views.company_edit, name='company_edit'),
    path('company/<int:pk>/delete/', views.company_delete, name='company_delete'),

    # 창고정보
    path('warehouse/', views.warehouse_list, name='warehouse_list'),
    path('warehouse/create/', views.warehouse_create, name='warehouse_create'),
    path('warehouse/<int:pk>/edit/', views.warehouse_edit, name='warehouse_edit'),
    path('warehouse/<int:pk>/delete/', views.warehouse_delete, name='warehouse_delete'),
    
]