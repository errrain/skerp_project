from django.urls import path
from . import views
from sales.waitsalse import views as waitsales_views
from sales.waitinspection import views as waitinspection_views
from sales.shipment import views as shipment_views  # 새 디렉터리 가정

app_name = 'sales'

urlpatterns = [
    path('order/create/', views.order_create, name='order_create'),
    path('order/', views.order_list, name='order_list'),  # 고객사 발주 관리
    path('order/edit/<int:pk>/', views.order_edit, name='order_edit'),
    path('order/delete/<int:pk>/', views.order_delete, name='order_delete'),
    path('search-products/', views.search_products, name='search_products'),

    # 검사대기 재고
    path(
        'waitinspection/list/',
        waitinspection_views.waitinspection_list,
        name='waitinspection_list',
    ),

    # 제품 재고 리스트
    path(
        'waitsales/list/',
        waitsales_views.product_stock_list,
        name='product_stock_list',
    ),

    # 출하 목록 (SH LOT 기준)
    path(
        'shipment/',
        shipment_views.shipment_list,
        name='shipment_list',
    ),

    # 출하 등록 (출하대기 재고 → 출하서 작성)
    path(
        'shipment/create/',
        shipment_views.shipment_create,
        name='shipment_create',
    ),

    # ✅ 출하 저장 (AJAX)
    path(
        'shipment/save/',
        shipment_views.shipment_save,
        name='shipment_save',
    ),

    # 출하 내역 확인 (상세)
    path(
        'shipment/<int:pk>/detail/',
        shipment_views.shipment_detail,
        name='shipment_detail',
    ),

    # 수주매칭 팝업 (AJAX/템플릿)
    path(
        'shipment/<int:shipment_id>/order-match/',
        shipment_views.order_match,
        name='shipment_order_match',
    ),

    path(
        "shipment/<int:pk>/update/",
        shipment_views.shipment_update,
        name="shipment_update",
    ),

    path(
        "shipment/<int:pk>/box_search/",
        shipment_views.shipment_box_search,
        name="shipment_box_search",
    ),

    path(
        "shipment/<int:pk>/detail/",
        shipment_views.shipment_detail,
        name="shipment_detail",
    ),

]
