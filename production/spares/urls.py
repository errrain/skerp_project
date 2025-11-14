# production/spares/urls.py

from django.urls import path
from . import views

app_name = "spares"

urlpatterns = [
    # 스페어파트 목록
    # /production/spares/
    path(
        "",
        views.sparepart_list,
        name="part_list",
    ),

    # 스페어파트 신규등록
    # /production/spares/create/
    path(
        "create/",
        views.sparepart_create,
        name="part_create",
    ),

    # 스페어파트 상세
    # /production/spares/1/
    path(
        "<int:pk>/",
        views.sparepart_detail,
        name="part_detail",
    ),

    # 스페어파트 기본정보 수정(POST 전용)
    # /production/spares/1/update/
    path(
        "<int:pk>/update/",
        views.sparepart_update,
        name="part_update",
    ),

    # 스페어파트 삭제(소프트 삭제)
    # /production/spares/1/delete/
    path(
        "<int:pk>/delete/",
        views.sparepart_delete,
        name="part_delete",
    ),

    # 입고 등록
    # /production/spares/1/stock-in/
    path(
        "<int:pk>/stock-in/",
        views.sparepart_stock_in,
        name="part_stock_in",
    ),

    # 사용(출고) 등록
    # /production/spares/1/stock-out/
    path(
        "<int:pk>/stock-out/",
        views.sparepart_stock_out,
        name="part_stock_out",
    ),
]
