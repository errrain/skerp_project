# production/chemadd/urls.py

from django.urls import path
from . import views

app_name = "chemadd"

urlpatterns = [
    # 약품 투입 헤더 목록
    # /production/chemadd/
    path(
        "",
        views.chemadd_list,
        name="chemadd_list",
    ),

    # 약품 투입 신규 등록
    # /production/chemadd/create/
    path(
        "create/",
        views.chemadd_create,
        name="chemadd_create",
    ),

    # 약품 투입 수정 (헤더 + 라인)
    # /production/chemadd/1/
    path(
        "<int:pk>/",
        views.chemadd_edit,
        name="chemadd_edit",
    ),

    # 약품 투입 삭제
    # /production/chemadd/1/delete/
    path(
        "<int:pk>/delete/",
        views.chemadd_delete,
        name="chemadd_delete",
    ),
]
