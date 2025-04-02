# vendor/urls.py
from django.urls import path

from vendor import views

app_name = 'vendor'  # ✅ 이 줄을 반드시 추가해야 namespace가 등록됨

urlpatterns = [
    path('', views.vendor_list, name='vendor_list'),
    path('create/', views.vendor_create, name='vendor_create'),
    path('<int:pk>/edit/', views.vendor_edit, name='vendor_edit'),
    path('<int:pk>/delete/', views.vendor_delete, name='vendor_delete'),
]