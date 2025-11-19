# production/nfadd/urls.py

from django.urls import path
from . import views

app_name = "nfadd"

urlpatterns = [
    # 비철 투입일지 목록
    # /production/nfadd/
    path(
        "",
        views.nfadd_list,
        name="nfadd_list",
    ),

    # 비철 투입일지 등록
    # /production/nfadd/create/
    path(
        "create/",
        views.nfadd_create,
        name="nfadd_create",
    ),

    # 비철 투입일지 수정
    # /production/nfadd/3/edit/
    path(
        "<int:pk>/edit/",
        views.nfadd_edit,
        name="nfadd_edit",
    ),

    # 비철 투입일지 삭제
    # /production/nfadd/3/delete/
    path(
        "<int:pk>/delete/",
        views.nfadd_delete,
        name="nfadd_delete",
    ),
]
