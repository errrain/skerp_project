# purchase/urls.py

from django.urls import path

# 사출(injection)
from .views import injection as inj
# 약/비/부 통합
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

    # ✅ 엑셀(CSV) 다운로드 (추가)
    path("injection/receipts/export/", inj.inj_receipt_export, name="inj_receipt_export"),

    # 출고
    path("injection/issues/", inj.issue_list, name="inj_issue_list"),
    path("injection/issues/<int:receipt_id>/add/", inj.issue_add, name="inj_issue_add"),
    path("injection/issues/add/", inj.issue_add_bulk, name="inj_issue_add_bulk"),

    # =========================
    # 사출 (Injection) - 수입검사 PASS 라인 기반
    # =========================
    # 후보 목록(발주 LOT 단위)
    path(
        "injection/receipts/<int:order_id>/candidates/",
        inj.receipt_candidates,
        name="inj_receipt_candidates",
    ),
    # 선택 라인 입고 확정(헤더 1 + 라인 N)
    path(
        "injection/receipts/<int:order_id>/commit/",
        inj.receipt_commit,
        name="inj_receipt_commit",
    ),
    # 선택 라인 입고 취소(ReceiptLine 기준)
    path(
        "injection/receipts/<int:order_id>/revert/",
        inj.receipt_revert,
        name="inj_receipt_revert",
    ),

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
    path("orders/<int:order_id>/update", uni.order_update, name="uni_order_update"),

    # 입고
    path("receipts/", uni.receipt_list, name="uni_receipt_list"),
    path("receipts/add", uni.receipt_add, name="uni_receipt_add"),

    # ✅ 통합 입고 후보/확정
    path(
        "receipts/<int:order_id>/candidates/",
        uni.receipt_candidates,
        name="uni_receipt_candidates",
    ),
    path(
        "receipts/<int:order_id>/commit/",
        uni.receipt_commit,
        name="uni_receipt_commit",
    ),

    # 출고
    path("issues/", uni.issue_list, name="uni_issue_list"),
    path("issues/add", uni.issue_add, name="uni_issue_add"),

    # 반품
    path("returns/", uni.return_list, name="uni_return_list"),
    path("returns/add", uni.return_add, name="uni_return_add"),

    # 사출 화면 조각
    path(
        "injection/issues/<int:receipt_id>/fragment/",
        inj.issue_group_fragment,
        name="inj_issue_group_fragment",
    ),

    # 발주서 출력
    path("orders/<int:order_id>/print/", uni.order_print, name="uni_order_print"),

    # 사용 처리 API
    path("receipts/usage/line/",    uni.usage_line_apply,    name="uni_usage_line_apply"),
    path("receipts/usage/receipt/", uni.usage_receipt_apply, name="uni_usage_receipt_apply"),

    path(
        "receipts/lines/<int:line_id>/edit/", uni.receipt_line_edit, name="uni_receipt_line_edit",
    ),

]
