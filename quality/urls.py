# quality/urls.py
from django.urls import path
from . import views
from .outgoing import views as outgoing_views  # 출하검사용 views

app_name = "quality"

urlpatterns = [
    # 수입검사 목록
    path("incoming/", views.incoming_list, name="incoming_list"),

    # 목록 엑셀(CSV) 다운로드
    path("incoming/export/", views.incoming_export, name="incoming_export"),

    # 검사 팝업(배송상세 반복)
    path(
        "incoming/<int:order_id>/inspect/",
        views.incoming_inspect_layer,
        name="incoming_inspect_layer",
    ),
    path(
        "incoming/<int:order_id>/inspect/save/",
        views.incoming_inspect_save,
        name="incoming_inspect_save",
    ),

    # ───────── 출하검사 ─────────

    # 출하검사 목록 (관리자용)
    path("outgoing/", outgoing_views.outgoing_list, name="outgoing_list"),

    # 출하검사 목록 (현장용)
    path(
        "outgoing/site/",
        outgoing_views.outgoing_site_list,
        name="outgoing_site_list",
    ),

    # 출하검사 상세 (관리자용)
    path(
        "outgoing/<int:workorder_id>/inspect/",
        outgoing_views.outgoing_inspect,
        name="outgoing_inspect",
    ),

    # 출하검사 상세 (현장용 – 같은 view, mode='site')
    path(
        "outgoing/site/<int:workorder_id>/inspect/",
        outgoing_views.outgoing_inspect,
        {"mode": "site"},
        name="outgoing_site_inspect",
    ),
]
