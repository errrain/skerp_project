# purchase/urls.py
from django.urls import path
from .views import injection as inj

app_name = "purchase"

urlpatterns = [
    # 목록
    path("injection/receipts/", inj.receipt_list, name="inj_receipt_list"),
    path("injection/receipts/<int:order_id>/add/", inj.receipt_add, name="inj_receipt_add"),
    path("injection/receipts/add/", inj.receipt_add, name="inj_receipt_add_bulk"),

    # 사출 출고
    path("injection/issues/", inj.issue_list, name="inj_issue_list"),
    # path("injection/issues/<int:order_id>/add/", inj.issue_add, name="inj_issue_add"),

    # 사출 반품
    path("injection/issues/", inj.issue_list, name="inj_issue_list"),
    path("injection/issues/<int:receipt_id>/add/", inj.issue_add, name="inj_issue_add"),
    path("injection/issues/add/", inj.issue_add_bulk, name="inj_issue_add_bulk"),
    # path("injection/returns/<int:order_id>/add/", inj.return_add, name="inj_return_add"),

    # 사출 출고(현장용)
    # path("injection/issues/shop/", inj.issue_shop, name="inj_issue_shop"),
]
