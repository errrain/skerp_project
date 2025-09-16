# purchase/urls.py
from django.urls import path

# 사출(injection) – 기존 유지
from .views import injection as inj
# 약/비/부 통합 – 새 뷰
from .views import unified as uni

app_name = "purchase"

urlpatterns = [
    # =========================
    # 사출 (Injection) - 기존
    # =========================
    # 입고
    path("injection/receipts/", inj.receipt_list, name="inj_receipt_list"),
    path("injection/receipts/<int:order_id>/add/", inj.receipt_add, name="inj_receipt_add"),
    path("injection/receipts/add/", inj.receipt_add, name="inj_receipt_add_bulk"),

    # 출고
    path("injection/issues/", inj.issue_list, name="inj_issue_list"),
    path("injection/issues/<int:receipt_id>/add/", inj.issue_add, name="inj_issue_add"),
    path("injection/issues/add/", inj.issue_add_bulk, name="inj_issue_add_bulk"),

    # =========================
    # 약품/비철/부자재 (통합)
    # =========================
    # 발주 목록/등록/저장
    path("orders/", uni.order_list, name="uni_order_list"),
    path("orders/form", uni.order_form, name="uni_order_form"),
    path("orders/get-items/", uni.order_get_items, name="uni_order_get_items"),  # AJAX 품목+단가
    path("orders/save", uni.order_save, name="uni_order_save"),

    # 엑셀(CSV) 다운로드 / 취소 / 수정
    path("orders/export", uni.order_export, name="uni_order_export"),
    path("orders/<int:order_id>/cancel", uni.order_cancel, name="uni_order_cancel"),
    path("orders/<int:order_id>/edit", uni.order_edit, name="uni_order_edit"),
    # ★★★ 추가: 업데이트(수정 저장)
    path("orders/<int:order_id>/update", uni.order_update, name="uni_order_update"),

    # 입고
    path("receipts/", uni.receipt_list, name="uni_receipt_list"),
    path("receipts/add", uni.receipt_add, name="uni_receipt_add"),

    # 출고
    path("issues/", uni.issue_list, name="uni_issue_list"),
    path("issues/add", uni.issue_add, name="uni_issue_add"),

    # 반품
    path("returns/", uni.return_list, name="uni_return_list"),
    path("returns/add", uni.return_add, name="uni_return_add"),
]
