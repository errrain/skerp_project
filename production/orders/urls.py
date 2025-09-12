# production/orders/urls.py
from django.urls import path
from . import views

app_name = "orders"

urlpatterns = [
    path("", views.order_list, name="order_list"),
    path("create/", views.order_create, name="order_create"),
    path("<int:pk>/edit/", views.order_edit, name="order_edit"),
    path("<int:pk>/delete/", views.order_delete, name="order_delete"),
    # ✅ AJAX: 수주 검색
    path("search-sales/", views.search_sales_orders, name="search_sales_orders"),
    # ★ 행 단위 인라인 저장
    path("row-update/<int:pk>/", views.order_row_update, name="order_row_update"),
    # ★ 순서 저장
    path("reorder/", views.order_reorder, name="order_reorder"),
    path("last-end/", views.get_last_end, name="last_end"),  # ★ 추가
]
