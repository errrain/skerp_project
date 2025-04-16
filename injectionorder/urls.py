from django.urls import path
from . import views

app_name = 'injectionorder'

urlpatterns = [
    path('', views.order_list, name='order_list'),                      # 목록
    path('add/', views.injection_order_create, name='order_create'),    # 등록
    path('edit/<int:order_id>/', views.injection_order_edit, name='order_edit'),
    path('get-injections/', views.get_injections_by_vendor, name='get_injections'),  # AJAX 엔드포인트

    # 아래는 모달 수정/삭제 구현 시 확장 예정
    path('edit/<int:order_id>/', views.injection_order_edit, name='order_edit'),
    # path('<int:pk>/delete/', views.order_delete, name='order_delete'),  # (예정) 삭제
]
