# quality/urls.py
from django.urls import path
from . import views

app_name = "quality"

urlpatterns = [
    # 수입검사 목록
    path("incoming/", views.incoming_list, name="incoming_list"),

    # 목록 엑셀(CSV) 다운로드
    path("incoming/export/", views.incoming_export, name="incoming_export"),

    # 검사 팝업(배송상세 반복)
    path("incoming/<int:order_id>/inspect/", views.incoming_inspect_layer, name="incoming_inspect_layer"),
    path("incoming/<int:order_id>/inspect/save/", views.incoming_inspect_save, name="incoming_inspect_save"),

]
