from django.urls import path
from . import views

app_name = 'rack'

urlpatterns = [
    path('', views.rack_master_list, name='rack_master_list'),  # 앱 루트 URL에 연결
    path('add/', views.rack_master_add, name='rack_master_add'),  # ← 추가!

    # ✅ 이 부분 추가
    path('<str:rack_master_id>/', views.rack_master_detail, name='rack_master_detail'),
    path('<str:rack_master_id>/add/', views.rack_detail_add, name='rack_detail_add'),
    path('detail/<int:pk>/edit/', views.rack_detail_edit, name='rack_detail_edit'),
    path('detail/<int:pk>/delete/', views.rack_detail_delete, name='rack_detail_delete'),
    path('<str:rack_master_id>/delete-image/', views.rack_master_image_delete, name='rack_master_image_delete'),
]
