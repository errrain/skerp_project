from django.urls import path
from . import views

# ✅ 템플릿/reverse에서 항상 'partner:...' 로 부를 수 있게 네임스페이스 고정
app_name = 'partner'

urlpatterns = [
    # 목록 + 엑셀
    path('orders/', views.OrderListView.as_view(), name='order_list'),
    path('export/', views.order_export, name='order_export'),

    # 상세(배송등록 화면)
    path('orders/<int:order_id>/', views.order_detail, name='order_detail'),

    # 부분출고(배송상세) 추가
    path('orders/<int:order_id>/shipments/add/', views.shipment_add, name='shipment_add'),

    # 부분출고(배송상세) 삭제 & QR 출력
    path('shipments/<int:group_id>/delete/', views.shipment_delete, name='shipment_delete'),
    path('shipments/<int:group_id>/qr/', views.shipment_qr, name='shipment_qr'),
]