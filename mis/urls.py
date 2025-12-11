# mis/urls.py
from django.urls import path
from .shipment import views as shipment_views
from .trace import views as trace_views

app_name = "mis"

urlpatterns = [
    # 경영정보 - 출하 통계
    path(
        "shipment/summary/",
        shipment_views.shipment_summary,
        name="shipment_summary",
    ),

    # LOT Trace 메인 화면
    path(
        "trace/",
        trace_views.lot_trace_page,
        name="lot_trace",
    ),

    # LOT Trace API (Mermaid 데이터)
    path(
        "trace/api/",
        trace_views.lot_trace_api,
        name="lot_trace_api",
    ),
]
