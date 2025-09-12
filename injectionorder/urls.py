#injectionorder/urls.py
from django.urls import path
from . import views

app_name = 'injectionorder'

urlpatterns = [
    path('', views.order_list, name='order_list'),
    path('add/', views.injection_order_create, name='order_create'),
    path('edit/<int:order_id>/', views.injection_order_edit, name='order_edit'),
    path('get-injections/', views.get_injections_by_vendor, name='get_injections'),

    # ⚡ 발주 취소 (구 delete 대체)
    path('cancel/<int:order_id>/', views.order_cancel, name='order_cancel'),

    # 🟢 엑셀(CSV) 다운로드
    path('export/', views.order_export, name='order_export'),
]