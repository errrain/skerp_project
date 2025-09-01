# quality/urls.py
from django.urls import path
from . import views

app_name = "quality"

urlpatterns = [
    path("incoming/", views.incoming_list, name="incoming_list"),

    # 팝업 레이어 열기
    path("incoming/<int:order_id>/inspect/", views.incoming_inspect_layer, name="incoming_inspect_layer"),

    # 팝업 저장
    path("incoming/<int:order_id>/inspect/save/", views.incoming_inspect_save, name="incoming_inspect_save"),

]
