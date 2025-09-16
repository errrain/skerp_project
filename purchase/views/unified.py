# purchase/views/unified.py
from datetime import date, datetime
from calendar import monthrange
from itertools import zip_longest

from django.urls import reverse
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.paginator import Paginator
from django.db import transaction, connection
from django.db.models import F, Q, Exists, OuterRef, Subquery, IntegerField
from django.http import (
    HttpResponseBadRequest,
    HttpResponseForbidden,
    JsonResponse,
    HttpResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.module_loading import import_string
from django.views.decorators.http import require_http_methods
from django.test.utils import CaptureQueriesContext

from master.models import Warehouse
from vendor.models import Vendor
from purchase.models import (
    UnifiedReceipt,
    UnifiedIssue,
    UnifiedReturn,
    UnifiedOrder,
    UnifiedOrderItem,
    CATEGORY_CHOICES,
)

# ── 품목/단가 모델 임포트 ──────────────────────────────────────────────
# 약품
from chemical.models import Chemical, ChemicalPrice
# 비철(앱명 nonferrous, 모델명은 Chemical/ChemicalPrice)
try:
    from nonferrous.models import Chemical as NFItem, ChemicalPrice as NFPrice
except Exception:
    NFItem, NFPrice = None, None
# 부자재
try:
    from submaterial.models import Submaterial, SubmaterialPrice
except Exception:
    Submaterial, SubmaterialPrice = None, None

# ──────────────────────────────────────────────────────────────────────────────
# LOT 헬퍼 (단일 정의)
# ──────────────────────────────────────────────────────────────────────────────
try:
    from utils.lot import get_next_lot
except Exception:
    try:
        from core.utils.lot import get_next_lot
    except Exception:
        from lot import get_next_lot  # 최후 fallback


# ──────────────────────────────────────────────────────────────────────────────
# 내부 유틸
# ──────────────────────────────────────────────────────────────────────────────
def _get_cat(request):
    """CHEM | NF | SUP 중 하나를 반환 (기본 CHEM)."""
    cat = (request.GET.get("cat") or request.POST.get("cat") or "").upper()
    valid = {c for c, _ in CATEGORY_CHOICES}
    return cat if cat in valid else "CHEM"


def _ct_for(app_label, model_name):
    """ContentType natural_key는 model을 소문자로 요구한다."""
    return ContentType.objects.get_by_natural_key(
        (app_label or "").lower(),
        (model_name or "").lower()
    )


def _ensure_vendor_scope(user, vendor_id: int) -> bool:
    """
    접근 정책:
      - 내부 사용자(is_internal=True): 모든 vendor OK
      - 외부 사용자: 본인 vendor 만 허용
    """
    is_internal = getattr(user, "is_internal", False)
    if is_internal:
        return True
    user_vendor_id = getattr(getattr(user, "vendor", None), "id", None)
    return bool(user_vendor_id and int(user_vendor_id) == int(vendor_id))


def _snapshot_from_item(item_obj):
    """품목 표시 스냅샷(이름/스펙) 생성."""
    name = (
        getattr(item_obj, "name", None)
        or getattr(item_obj, "item_name", None)
        or getattr(item_obj, "title", None)
        or str(item_obj)
    )
    spec = (
        getattr(item_obj, "spec", None)
        or getattr(item_obj, "spec_name", None)
        or getattr(item_obj, "model", None)
        or ""
    )
    return str(name)[:200], str(spec)[:200]


def _month_defaults(today: date):
    """이번달 1일 ~ 말일 ISO 문자열 반환."""
    start = today.replace(day=1)
    end = today.replace(day=monthrange(today.year, today.month)[1])
    return start.isoformat(), end.isoformat()


def _qs_sql(qs):
    """QuerySet SQL 문자열을 최대한 안전하게 추출."""
    try:
        return str(qs.query)
    except Exception:
        list(qs[:1])
        try:
            return connection.queries[-1]["sql"]
        except Exception:
            return "(cannot introspect SQL)"


# ──────────────────────────────────────────────────────────────────────────────
# 카테고리별 품목 모델 & '벤더 FK 필드' 매핑
# ──────────────────────────────────────────────────────────────────────────────
ITEM_MODEL_MAP = {
    # app, model, vendor_fk, name_field
    "CHEM": {"app": "chemical",    "model": "Chemical",    "vendor_fk": "customer", "name": "name"},
    "NF":   {"app": "nonferrous",  "model": "Chemical",    "vendor_fk": "customer", "name": "name"},
    "SUP":  {"app": "submaterial", "model": "Submaterial", "vendor_fk": "customer", "name": "name"},
}


def _vendors_for_cat(cat: str):
    """발주처 드롭다운 데이터."""
    vendor_fields = {f.name for f in Vendor._meta.get_fields()}
    tx_field = "transaction_type" if "transaction_type" in vendor_fields else (
        "trade_type" if "trade_type" in vendor_fields else None
    )

    base = Vendor.objects.all()
    if tx_field:
        base = base.filter(
            Q(**{f"{tx_field}__iexact": "BUY"})  |
            Q(**{f"{tx_field}__iexact": "BOTH"}) |
            Q(**{f"{tx_field}__icontains": "매입"}) |
            Q(**{f"{tx_field}__icontains": "병행"})
        )

    qs = base.filter(major_items__code=cat).distinct().order_by("name")
    if qs.exists():
        return qs

    try:
        m = ITEM_MODEL_MAP[cat]
        ct = ContentType.objects.get_by_natural_key(m["app"], m["model"].lower())
        Model = ct.model_class()
        fk = m["vendor_fk"]
        sub = Model.objects.filter(**{f"{fk}_id": OuterRef("pk")})
        return base.annotate(has_items=Exists(sub)).filter(has_items=True).distinct().order_by("name")
    except Exception:
        return base.distinct().order_by("name")


def _cancel_code():
    """
    UnifiedOrder.order_status의 choices에서 '취소' 혹은 'cancel' 라벨/코드를 찾아 반환.
    없으면 'CANCEL'→'CNL'→현재값 그대로 순으로 보수적으로 처리.
    """
    field = UnifiedOrder._meta.get_field("order_status")
    choices = list(field.choices or [])
    # 라벨/코드에 '취소' 또는 'cancel' 포함 우선 탐색
    for code, label in choices:
        text = f"{code}|{label}".lower()
        if "취소" in str(label) or "cancel" in text:
            return code
    # 흔한 코드들 시도
    for guess in ("CANCEL", "CNL"):
        if any(code == guess for code, _ in choices):
            return guess
    # 마지막 수단: 현재값 유지용 None
    return None


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                              발주 목록                                   ║
# ╚══════════════════════════════════════════════════════════════════════════╝
@require_http_methods(["GET"])
def order_list(request):
    cat = (request.GET.get("cat") or "CHEM").upper()

    today = date.today()
    def_start, def_end = _month_defaults(today)
    order_date_start = request.GET.get("order_date_start") or def_start
    order_date_end = request.GET.get("order_date_end") or def_end
    expected_date_start = request.GET.get("expected_date_start") or ""
    expected_date_end = request.GET.get("expected_date_end") or ""

    vendor_kw = (request.GET.get("vendor") or "").strip()
    product_kw = (request.GET.get("product") or "").strip()
    order_status_kw = (request.GET.get("order_status") or "").strip()
    flow_status_kw = (request.GET.get("flow_status") or "").strip()

    qs = (
        UnifiedOrderItem.objects.select_related("order", "order__vendor")
        .filter(order__category=cat, order__is_deleted=False)
    )
    if order_date_start:
        qs = qs.filter(order__order_date__gte=order_date_start)
    if order_date_end:
        qs = qs.filter(order__order_date__lte=order_date_end)
    if expected_date_start:
        qs = qs.filter(expected_date__gte=expected_date_start)
    if expected_date_end:
        qs = qs.filter(expected_date__lte=expected_date_end)
    if vendor_kw:
        qs = qs.filter(order__vendor__name__icontains=vendor_kw)
    if product_kw:
        qs = qs.filter(item_name_snapshot__icontains=product_kw)
    if order_status_kw:
        qs = qs.filter(order__order_status=order_status_kw)
    if flow_status_kw:
        qs = qs.filter(order__flow_status=flow_status_kw)

    qs = qs.annotate(total_price=F("amount"))

    paginator = Paginator(qs.order_by("-order__order_date", "-order_id", "id"), 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    preserved = [
        "order_date_start", "order_date_end",
        "expected_date_start", "expected_date_end",
        "vendor", "product",
        "order_status", "flow_status",
        "cat",
    ]
    querystring = "&join;".join(
        [f"{k}={request.GET.get(k)}" for k in preserved if request.GET.get(k)]
    ).replace("&join;", "&")

    ctx = {
        "cat": cat,
        "order_items": page_obj.object_list,
        "page_obj": page_obj,
        "order_status_choices": UnifiedOrder._meta.get_field("order_status").choices,
        "flow_status_choices": UnifiedOrder._meta.get_field("flow_status").choices,
        "order_date_start_default": def_start,
        "order_date_end_default": def_end,
        "expected_date_start_default": "",
        "expected_date_end_default": "",
        "querystring": querystring,
        "request": request,
    }
    return render(request, "purchase/unified/orders/list.html", ctx)


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                             입고 목록 / 등록                             ║
# ╚══════════════════════════════════════════════════════════════════════════╝
@require_http_methods(["GET"])
def receipt_list(request):
    cat = _get_cat(request)
    qs = (
        UnifiedReceipt.objects.select_related("vendor", "warehouse")
        .filter(category=cat, is_deleted=False)
    )

    if not getattr(request.user, "is_internal", False):
        user_vendor_id = getattr(getattr(request.user, "vendor", None), "id", None)
        if not user_vendor_id:
            return HttpResponseForbidden("No vendor bound to user")
        qs = qs.filter(vendor_id=user_vendor_id)

    vendor_kw = (request.GET.get("vendor") or "").strip()
    item_kw = (request.GET.get("item") or "").strip()
    wh_id = (request.GET.get("warehouse_id") or "").strip()
    date_f = (request.GET.get("date_from") or "").strip()
    date_t = (request.GET.get("date_to") or "").strip()

    if vendor_kw:
        qs = qs.filter(vendor__name__icontains=vendor_kw)
    if item_kw:
        qs = qs.filter(item_name_snapshot__icontains=item_kw)
    if wh_id.isdigit():
        qs = qs.filter(warehouse_id=int(wh_id))
    if date_f:
        qs = qs.filter(date__gte=date_f)
    if date_t:
        qs = qs.filter(date__lte=date_t)

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "purchase/unified/receipts/list.html",
        {
            "cat": cat,
            "page_obj": page_obj,
            "page_range": paginator.get_elided_page_range(number=page_obj.number),
            "filter": request.GET,
        },
    )


@require_http_methods(["POST"])
@login_required
@transaction.atomic
def receipt_add(request):
    """
    필수 POST:
      cat, vendor_id, item_app, item_model, item_id, qty, date(YYYY-MM-DD), warehouse_id
      remark? (선택)
    """
    cat = _get_cat(request)
    try:
        vendor_id = int(request.POST["vendor_id"])
        if not _ensure_vendor_scope(request.user, vendor_id):
            return HttpResponseForbidden("Vendor scope violation")

        item_ct = _ct_for(request.POST["item_app"], request.POST["item_model"])
        item_id = int(request.POST["item_id"])
        qty = int(request.POST["qty"])
        if qty <= 0:
            return HttpResponseBadRequest("qty must be > 0")

        rdate_str = (request.POST.get("date") or "").strip() or datetime.now().strftime("%Y-%m-%d")
        rdate = datetime.strptime(rdate_str, "%Y-%m-%d").date()

        wh = Warehouse.objects.get(pk=int(request.POST["warehouse_id"]))
        vendor = Vendor.objects.get(pk=vendor_id)

    except Exception as e:
        return HttpResponseBadRequest(f"Invalid payload: {e}")

    lot = get_next_lot("IN", rdate)

    item_obj = item_ct.get_object_for_this_type(pk=item_id)
    item_name, item_spec = _snapshot_from_item(item_obj)

    UnifiedReceipt.objects.create(
        receipt_lot=lot,
        date=rdate,
        qty=qty,
        remark=(request.POST.get("remark") or "").strip(),
        created_by=request.user,
        category=cat,
        vendor=vendor,
        item_ct=item_ct,
        item_id=item_id,
        warehouse=wh,
        is_used=False,
        item_name_snapshot=item_name,
        spec_snapshot=item_spec,
        extra={},
    )

    messages.success(request, f"[{cat}] 입고 등록 완료 · LOT={lot}")
    return redirect(f"{request.path}?cat={cat}")


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                           출고(창고이동) 목록 / 등록                      ║
# ╚══════════════════════════════════════════════════════════════════════════╝
@require_http_methods(["GET"])
def issue_list(request):
    cat = _get_cat(request)
    qs = (
        UnifiedIssue.objects.select_related("receipt", "from_warehouse", "to_warehouse")
        .filter(category=cat)
    )

    if not getattr(request.user, "is_internal", False):
        user_vendor_id = getattr(getattr(request.user, "vendor", None), "id", None)
        if not user_vendor_id:
            return HttpResponseForbidden("No vendor bound to user")
        qs = qs.filter(receipt__vendor_id=user_vendor_id)

    lot_kw = (request.GET.get("lot") or "").strip()
    wh_from = (request.GET.get("from_warehouse_id") or "").strip()
    wh_to = (request.GET.get("to_warehouse_id") or "").strip()
    date_f = (request.GET.get("date_from") or "").strip()
    date_t = (request.GET.get("date_to") or "").strip()

    if lot_kw:
        qs = qs.filter(receipt_lot__icontains=lot_kw)
    if wh_from.isdigit():
        qs = qs.filter(from_warehouse_id=int(wh_from))
    if wh_to.isdigit():
        qs = qs.filter(to_warehouse_id=int(wh_to))
    if date_f:
        qs = qs.filter(date__gte=date_f)
    if date_t:
        qs = qs.filter(date__lte=date_t)

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "purchase/unified/issues/list.html",
        {
            "cat": cat,
            "page_obj": page_obj,
            "page_range": paginator.get_elided_page_range(number=page_obj.number),
            "filter": request.GET,
        },
    )


@require_http_methods(["POST"])
@login_required
@transaction.atomic
def issue_add(request):
    """
    필수 POST:
      cat, receipt_id, to_warehouse_id, date(YYYY-MM-DD), qty(전량 이동 권장)
      remark? (선택), is_used_at_issue? (선택: 'on')
    """
    cat = _get_cat(request)
    try:
        receipt = get_object_or_404(
            UnifiedReceipt, pk=int(request.POST["receipt_id"]), is_deleted=False
        )
        if not _ensure_vendor_scope(request.user, receipt.vendor_id):
            return HttpResponseForbidden("Vendor scope violation")

        qty = int(request.POST["qty"])
        if qty <= 0:
            return HttpResponseBadRequest("qty must be > 0")

        if qty != receipt.qty:
            return HttpResponseBadRequest("Only full-quantity move is allowed at this phase")

        to_wh = Warehouse.objects.get(pk=int(request.POST["to_warehouse_id"]))
        if to_wh.id == receipt.warehouse_id:
            return HttpResponseBadRequest("from/to warehouse must be different")

        idate_str = (request.POST.get("date") or "").strip() or datetime.now().strftime("%Y-%m-%d")
        idate = datetime.strptime(idate_str, "%Y-%m-%d").date()

    except Exception as e:
        return HttpResponseBadRequest(f"Invalid payload: {e}")

    lot = get_next_lot("OT", idate)

    UnifiedIssue.objects.create(
        receipt_lot=lot,
        date=idate,
        qty=qty,
        remark=(request.POST.get("remark") or "").strip(),
        created_by=request.user,
        category=cat,
        receipt=receipt,
        from_warehouse_id=receipt.warehouse_id,
        to_warehouse=to_wh,
        is_used_at_issue=bool(request.POST.get("is_used_at_issue")),
    )

    receipt.warehouse_id = to_wh.id
    receipt.save(update_fields=["warehouse"])

    messages.success(request, f"[{cat}] 창고이동 등록 완료 · LOT={lot}")
    return redirect(f"{request.path}?cat={cat}")


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                              반품 목록 / 등록                             ║
# ╚══════════════════════════════════════════════════════════════════════════╝
@require_http_methods(["GET"])
def return_list(request):
    cat = _get_cat(request)
    qs = (
        UnifiedReturn.objects.select_related("receipt", "from_warehouse")
        .filter(category=cat)
    )

    if not getattr(request.user, "is_internal", False):
        user_vendor_id = getattr(getattr(request.user, "vendor", None), "id", None)
        if not user_vendor_id:
            return HttpResponseForbidden("No vendor bound to user")
        qs = qs.filter(receipt__vendor_id=user_vendor_id)

    lot_kw = (request.GET.get("lot") or "").strip()
    wh_from = (request.GET.get("from_warehouse_id") or "").strip()
    date_f = (request.GET.get("date_from") or "").strip()
    date_t = (request.GET.get("date_to") or "").strip()

    if lot_kw:
        qs = qs.filter(receipt_lot__icontains=lot_kw)
    if wh_from.isdigit():
        qs = qs.filter(from_warehouse_id=int(wh_from))
    if date_f:
        qs = qs.filter(date__gte=date_f)
    if date_t:
        qs = qs.filter(date__lte=date_t)

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "purchase/unified/returns/list.html",
        {
            "cat": cat,
            "page_obj": page_obj,
            "page_range": paginator.get_elided_page_range(number=page_obj.number),
            "filter": request.GET,
        },
    )


@require_http_methods(["POST"])
@login_required
@transaction.atomic
def return_add(request):
    """
    필수 POST:
      cat, receipt_id, date(YYYY-MM-DD)
      remark? (선택) reason_code? (선택)
    """
    cat = _get_cat(request)
    try:
        receipt = get_object_or_404(
            UnifiedReceipt, pk=int(request.POST["receipt_id"]), is_deleted=False
        )
        if not _ensure_vendor_scope(request.user, receipt.vendor_id):
            return HttpResponseForbidden("Vendor scope violation")

        qty = receipt.qty

        rdate_str = (request.POST.get("date") or "").strip() or datetime.now().strftime("%Y-%m-%d")
        rdate = datetime.strptime(rdate_str, "%Y-%m-%d").date()

    except Exception as e:
        return HttpResponseBadRequest(f"Invalid payload: {e}")

    lot = get_next_lot("OT", rdate)

    UnifiedReturn.objects.create(
        receipt_lot=lot,
        date=rdate,
        qty=qty,
        remark=(request.POST.get("remark") or "").strip(),
        created_by=request.user,
        category=cat,
        receipt=receipt,
        from_warehouse_id=receipt.warehouse_id,
        reason_code=(request.POST.get("reason_code") or "").strip(),
    )

    receipt.is_active = False
    receipt.is_deleted = True
    receipt.save(update_fields=["is_active", "is_deleted"])

    messages.success(request, f"[{cat}] 반품 등록 완료 · LOT={lot}")
    return redirect(f"{request.path}?cat={cat}")


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                    발주 등록(폼/저장) & 품목 AJAX 로드                    ║
# ╚══════════════════════════════════════════════════════════════════════════╝
@require_http_methods(["GET"])
def order_form(request):
    """발주 등록 화면 — 신규 작성."""
    cat = _get_cat(request)
    vendors = _vendors_for_cat(cat)
    ctx = {
        "cat": cat,
        "vendors": vendors,
        "today": date.today().isoformat(),
        "form_action": reverse("purchase:uni_order_save"),
        "edit_mode": False,
        "preset": {},  # 신규는 프리셋 없음
    }
    return render(request, "purchase/unified/orders/form.html", ctx)


@require_http_methods(["POST"])
@login_required
@transaction.atomic
def order_save(request):
    """
    신규 저장:
      cat, vendor_id, order_date, due_date?, header_remark?
      item_app[], item_model[], item_id[], qty[], unit_price[], expected_date[], item_remark[]
    """
    cat = _get_cat(request)

    try:
        vendor = Vendor.objects.get(pk=int(request.POST.get("vendor_id")))
        order_date = datetime.strptime(
            (request.POST.get("order_date") or date.today().isoformat()), "%Y-%m-%d"
        ).date()
        due_date = (
            datetime.strptime(request.POST.get("due_date"), "%Y-%m-%d").date()
            if request.POST.get("due_date") else None
        )
    except Exception as e:
        return HttpResponseBadRequest(f"Invalid header: {e}")

    order_lot = get_next_lot("PO", order_date)

    order_kwargs = dict(
        category=cat, vendor=vendor,
        order_lot=order_lot, order_date=order_date, due_date=due_date,
        created_by=request.user,
    )
    if hasattr(UnifiedOrder, "remark"):
        order_kwargs["remark"] = (request.POST.get("header_remark") or "").strip()

    order = UnifiedOrder.objects.create(**order_kwargs)

    created_cnt = _upsert_order_items_from_post(request, order, cat, replace=False)

    if created_cnt == 0:
        order.delete()
        return HttpResponseBadRequest("유효한 아이템이 없습니다.")

    messages.success(request, f"[{cat}] 발주 저장 완료 · LOT={order_lot} · 품목수={created_cnt}")
    return redirect(f"/purchase/orders/?cat={cat}")


# ── 수정 폼 (프리필) ────────────────────────────────────────────────────────
@require_http_methods(["GET"])
def order_edit(request, order_id: int):
    """
    기존 발주 수정 폼 — form.html을 재사용하되 프리셋을 내려준다.
    """
    order = get_object_or_404(UnifiedOrder, pk=order_id, is_deleted=False)
    cat = order.category

    # 취소/확정 등 편집 불가 조건 차단(사출 UX와 동일)
    if order.order_status != "NEW" or order.cancel_at:
        messages.warning(request, "이미 취소/진행된 발주는 수정할 수 없습니다.")
        return redirect(f"{reverse('purchase:uni_order_list')}?cat={cat}")

    # 드롭다운에 반드시 기존 벤더가 보이도록 보강
    qs = _vendors_for_cat(cat)
    vendors = list(qs)
    if order.vendor_id not in [v.id for v in vendors]:
        vendors.insert(0, order.vendor)

    # 아이템 프리셋
    preset_items = []
    for it in UnifiedOrderItem.objects.filter(order=order).order_by("id"):
        preset_items.append({
            "item_id": it.item_id,
            "qty": it.qty,
            "unit_price": float(it.unit_price or 0),
            "expected_date": it.expected_date.isoformat() if it.expected_date else "",
            "remark": it.remark or "",
        })

    ctx = {
        "cat": cat,
        "vendors": vendors,
        "today": order.order_date.isoformat(),
        "form_action": reverse("purchase:uni_order_update", args=[order.id]),
        "edit_mode": True,
        "preset": {
            "vendor_id": order.vendor_id,
            "order_date": order.order_date.isoformat(),
            "header_remark": getattr(order, "remark", "") or "",
            "items": preset_items,
        },
    }
    return render(request, "purchase/unified/orders/form.html", ctx)


# ── 수정 저장 ───────────────────────────────────────────────────────────────
@require_http_methods(["POST"])
@login_required
@transaction.atomic
def order_update(request, order_id: int):
    """
    기존 발주 업데이트 — 간단/안전: 기존 아이템 전부 삭제 후 재생성.
    """
    order = get_object_or_404(UnifiedOrder, pk=order_id, is_deleted=False)
    cat = order.category
    if order.order_status != "NEW" or order.cancel_at:
        return HttpResponseBadRequest("이미 취소/진행된 발주는 수정할 수 없습니다.")

    try:
        vendor = Vendor.objects.get(pk=int(request.POST.get("vendor_id")))
        order_date = datetime.strptime(
            (request.POST.get("order_date") or date.today().isoformat()), "%Y-%m-%d"
        ).date()
        due_date = (
            datetime.strptime(request.POST.get("due_date"), "%Y-%m-%d").date()
            if request.POST.get("due_date") else None
        )
    except Exception as e:
        return HttpResponseBadRequest(f"Invalid header: {e}")

    # 헤더 업데이트
    order.vendor = vendor
    order.order_date = order_date
    order.due_date = due_date
    if hasattr(order, "remark"):
        order.remark = (request.POST.get("header_remark") or "").strip()
    order.updated_by = request.user
    order.save()

    # 아이템 싹 지우고 다시 작성
    UnifiedOrderItem.objects.filter(order=order).delete()
    created_cnt = _upsert_order_items_from_post(request, order, cat, replace=False)
    if created_cnt == 0:
        return HttpResponseBadRequest("유효한 아이템이 없습니다.")

    messages.success(request, f"[{cat}] 발주 수정 완료 · LOT={order.order_lot} · 품목수={created_cnt}")
    return redirect(f"{reverse('purchase:uni_order_list')}?cat={cat}")


def _upsert_order_items_from_post(request, order, cat: str, replace: bool) -> int:
    """
    POST 배열에서 항목을 읽어 UnifiedOrderItem을 생성.
    replace=True 면 기존 항목 전부 삭제 후 재생성.
    """
    from itertools import zip_longest
    item_apps   = request.POST.getlist("item_app[]")
    item_models = request.POST.getlist("item_model[]")
    item_ids    = request.POST.getlist("item_id[]")
    qtys        = request.POST.getlist("qty[]")
    unit_prices = request.POST.getlist("unit_price[]")
    exps        = request.POST.getlist("expected_date[]")
    iremarks    = request.POST.getlist("item_remark[]")

    rows = zip_longest(item_apps, item_models, item_ids, qtys, unit_prices, exps, iremarks, fillvalue="")

    if replace:
        UnifiedOrderItem.objects.filter(order=order).delete()

    created_cnt = 0
    for app, model, iid, qty, up, exp, irem in rows:
        app = (app or "").strip().lower()
        model = (model or "").strip().lower()
        if not (app and model and iid and qty):
            continue
        try:
            ct = ContentType.objects.get_by_natural_key(app, model)
            iid = int(iid)
            q   = int(qty)
            upf = float(up) if str(up).strip() != "" else _suggest_unit_price(cat, iid)
            exp_date = datetime.strptime(exp, "%Y-%m-%d").date() if exp else None

            obj = ct.get_object_for_this_type(pk=iid)
            name = (getattr(obj, "name", None) or getattr(obj, "item_name", None) or str(obj))[:200]
            spec = (getattr(obj, "spec", None) or getattr(obj, "spec_name", None) or "")[:200]

            amount = round(q * upf, 4)
            item_kwargs = dict(
                order=order, item_ct=ct, item_id=iid,
                qty=q, unit_price=upf, amount=amount,
                expected_date=exp_date,
                item_name_snapshot=name, spec_snapshot=spec,
            )
            if hasattr(UnifiedOrderItem, "remark"):
                item_kwargs["remark"] = (irem or "").strip()

            UnifiedOrderItem.objects.create(**item_kwargs)
            created_cnt += 1
        except Exception:
            continue

    return created_cnt


# ── 취소 (사출과 동일 UX: 확인 후 상태 변경 + 취소일/자 기록) ───────────────
@require_http_methods(["POST"])
@login_required
@transaction.atomic
def order_cancel(request, order_id: int):
    order = get_object_or_404(UnifiedOrder, pk=order_id, is_deleted=False)
    cat = order.category

    if order.cancel_at:
        messages.info(request, "이미 취소된 발주입니다.")
        return redirect(f"{reverse('purchase:uni_order_list')}?cat={cat}")

    if order.order_status != "NEW":
        messages.warning(request, "진행중/완료된 발주는 취소할 수 없습니다.")
        return redirect(f"{reverse('purchase:uni_order_list')}?cat={cat}")

    code = _cancel_code()
    if code:
        order.order_status = code
    order.cancel_at = timezone.now()
    order.cancel_by = request.user
    order.save(update_fields=["order_status", "cancel_at", "cancel_by"])

    messages.success(request, "해당 발주를 취소했습니다.")
    return redirect(f"{reverse('purchase:uni_order_list')}?cat={cat}")


# ── (옵션) 엑셀/CSV 다운로드 ────────────────────────────────────────────────
@require_http_methods(["GET"])
def order_export(request):
    """
    현재 필터 조건 그대로 CSV로 내려줌.
    """
    cat = (request.GET.get("cat") or "CHEM").upper()
    request.GET = request.GET.copy()
    request.GET["cat"] = cat
    # 목록과 동일하게 데이터 구성
    today = date.today()
    def_start, def_end = _month_defaults(today)

    qs = (
        UnifiedOrderItem.objects.select_related("order", "order__vendor")
        .filter(order__category=cat, order__is_deleted=False)
    )

    if request.GET.get("order_date_start") or def_start:
        qs = qs.filter(order__order_date__gte=request.GET.get("order_date_start", def_start))
    if request.GET.get("order_date_end") or def_end:
        qs = qs.filter(order__order_date__lte=request.GET.get("order_date_end", def_end))
    if request.GET.get("expected_date_start"):
        qs = qs.filter(expected_date__gte=request.GET.get("expected_date_start"))
    if request.GET.get("expected_date_end"):
        qs = qs.filter(expected_date__lte=request.GET.get("expected_date_end"))
    if request.GET.get("vendor"):
        qs = qs.filter(order__vendor__name__icontains=request.GET.get("vendor"))
    if request.GET.get("product"):
        qs = qs.filter(item_name_snapshot__icontains=request.GET.get("product"))
    if request.GET.get("order_status"):
        qs = qs.filter(order__order_status=request.GET.get("order_status"))
    if request.GET.get("flow_status"):
        qs = qs.filter(order__flow_status=request.GET.get("flow_status"))

    import csv
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="orders_{cat}_{today.isoformat()}.csv"'
    writer = csv.writer(resp)
    writer.writerow([
        "LOT", "발주처", "발주일", "품명", "수량", "단가", "금액",
        "입고예정일", "발주상태", "진행상태", "등록일시", "수정일시"
    ])
    for it in qs.order_by("-order__order_date", "-order_id", "id"):
        o = it.order
        writer.writerow([
            o.order_lot, getattr(o.vendor, "name", "-"),
            o.order_date, it.item_name_snapshot, it.qty,
            it.unit_price, it.amount, it.expected_date,
            o.get_order_status_display(), o.get_flow_status_display(),
            o.created_at, o.updated_at,
        ])
    return resp


# ---------------------------------------------------------------------
# 품목 목록(AJAX) + 단가 서브쿼리
# ---------------------------------------------------------------------
@require_http_methods(["GET"])
def order_get_items(request):
    """
    GET /purchase/orders/get-items/?vendor_id=10&cat=CHEM[&debug=1]
    응답: { items: [...], sql?: ["SELECT ...", ...] }  # debug=1일 때만 sql 리스트 포함
    """
    try:
        cat = (request.GET.get("cat") or "CHEM").upper()
        vendor_id = int(request.GET.get("vendor_id"))
    except Exception:
        return JsonResponse({"items": [], "error": "잘못된 요청"}, status=400)

    debug = request.GET.get("debug") == "1"
    today = date.today().isoformat()
    items = []
    sql_list = []

    def _print_queries(label, ctx):
        for i, q in enumerate(ctx.captured_queries, 1):
            sql = q.get("sql", "")
            tm  = q.get("time", "-")
            print(f"[unified.order_get_items:{label}] #{i} ({tm}s)\n{sql}\n")
            sql_list.append(sql)

    if cat == "CHEM":
        latest_price_sq = ChemicalPrice.objects.filter(
            chemical_id=OuterRef("pk")
        ).order_by("-date").values("price")[:1]

        qs = (
            Chemical.objects
            .filter(customer_id=vendor_id, delete_yn="N", use_yn="Y")
            .annotate(unit_price=Subquery(latest_price_sq, output_field=IntegerField()))
            .values("id", "name", "spec", "unit_price")
        )
        with CaptureQueriesContext(connection) as ctx:
            rows = list(qs)
        _print_queries(f"{cat}", ctx)

        for r in rows:
            items.append({
                "id": r["id"],
                "name": f'{r["name"]}{(" " + r["spec"]) if r["spec"] else ""}',
                "unit_price": int(r["unit_price"] or 0),
                "today": today,
            })

    elif cat == "NF" and NFItem is not None:
        if NFPrice is not None:
            latest_price_sq = NFPrice.objects.filter(
                nonferrous_id=OuterRef("pk")
            ).order_by("-date").values("price")[:1]
            qs = (
                NFItem.objects.filter(customer_id=vendor_id, delete_yn="N", use_yn="Y")
                .annotate(unit_price=Subquery(latest_price_sq, output_field=IntegerField()))
                .values("id", "name", "spec", "unit_price")
            )
        else:
            qs = NFItem.objects.filter(customer_id=vendor_id, delete_yn="N", use_yn="Y") \
                               .values("id", "name", "spec")

        with CaptureQueriesContext(connection) as ctx:
            rows = list(qs)
        _print_queries(f"{cat}", ctx)

        for r in rows:
            items.append({
                "id": r["id"],
                "name": f'{r["name"]}{(" " + r.get("spec","")) if r.get("spec") else ""}',
                "unit_price": int(r.get("unit_price") or 0),
                "today": today,
            })

    elif cat == "SUP" and Submaterial is not None:
        if SubmaterialPrice is not None:
            latest_price_sq = SubmaterialPrice.objects.filter(
                submaterial_id=OuterRef("pk")
            ).order_by("-date").values("price")[:1]
            qs = (
                Submaterial.objects.filter(customer_id=vendor_id)
                .annotate(unit_price=Subquery(latest_price_sq, output_field=IntegerField()))
                .values("id", "name", "spec", "unit_price")
            )
        else:
            qs = Submaterial.objects.filter(customer_id=vendor_id).values("id", "name", "spec")

        with CaptureQueriesContext(connection) as ctx:
            rows = list(qs)
        _print_queries(f"{cat}", ctx)

        for r in rows:
            items.append({
                "id": r["id"],
                "name": f'{r["name"]}{(" " + r.get("spec","")) if r.get("spec") else ""}',
                "unit_price": int(r.get("unit_price") or 0),
                "today": today,
            })

    payload = {"items": items}
    if debug:
        payload["sql"] = sql_list
    return JsonResponse(payload)


# ---------------------------------------------------------------------
# 최신 단가 제안
# ---------------------------------------------------------------------
def _suggest_unit_price(cat: str, item_id: int) -> float:
    try:
        if cat == "CHEM":
            p = ChemicalPrice.objects.filter(chemical_id=item_id).order_by("-date").first()
            return float(getattr(p, "price", 0) or 0)
        elif cat == "NF" and NFPrice is not None:
            p = NFPrice.objects.filter(nonferrous_id=item_id).order_by("-date").first()
            return float(getattr(p, "price", 0) or 0)
        elif cat == "SUP" and SubmaterialPrice is not None:
            p = SubmaterialPrice.objects.filter(submaterial_id=item_id).order_by("-date").first()
            return float(getattr(p, "price", 0) or 0)
    except Exception:
        return 0.0
    return 0.0


# (옵션) import_string 기반 일반화 최신가
def _latest_price(price_model_path: str, fk_name: str, item_id: int) -> float:
    try:
        PriceModel = import_string(price_model_path)
    except Exception:
        return 0.0

    try:
        qs = PriceModel.objects.filter(**{fk_name: item_id}).order_by("-id")
        p = qs.first()
        if not p:
            return 0.0
        for field in ("price", "unit_price", "cost", "amount"):
            val = getattr(p, field, None)
            if val is not None:
                try:
                    return float(val)
                except Exception:
                    continue
        return 0.0
    except Exception:
        return 0.0

# =========================
# 발주 수정 화면 (프리셋 제공)
# =========================
@require_http_methods(["GET"])
def order_edit(request, order_id: int):
    order = get_object_or_404(UnifiedOrder, pk=order_id, is_deleted=False)
    cat = order.category  # 탭 연동은 주문의 카테고리 기준

    # 목록에 보이는 벤더만 기본으로, 기존 벤더가 필터에서 빠져도 드롭다운엔 포함되게 처리
    qs = _vendors_for_cat(cat)
    vendors = list(qs)
    if order.vendor_id not in [v.id for v in vendors]:
        vendors.insert(0, order.vendor)  # 최상단에 기존 벤더 추가

    # 아이템 프리셋
    items = list(
        UnifiedOrderItem.objects
        .filter(order=order)
        .values("item_id", "qty", "unit_price", "expected_date", "remark")
    )
    # expected_date를 문자열로 변환
    for x in items:
        x["expected_date"] = x["expected_date"].strftime("%Y-%m-%d") if x["expected_date"] else ""

    preset = {
        "vendor_id": order.vendor_id,
        "order_date": order.order_date.strftime("%Y-%m-%d"),
        "header_remark": getattr(order, "remark", "") or "",
        "items": items,
    }

    ctx = {
        "cat": cat,
        "vendors": vendors,
        # form.html 이 신규/수정 겸용으로 동작하도록 컨텍스트 제공
        "today": order.order_date.strftime("%Y-%m-%d"),
        "edit_mode": True,
        "form_action": reverse("purchase:uni_order_update", args=[order.id]),
        "preset": preset,
    }
    return render(request, "purchase/unified/orders/form.html", ctx)


# =========================
# 발주 수정 저장
# =========================
@require_http_methods(["POST"])
@login_required
@transaction.atomic
def order_update(request, order_id: int):
    order = get_object_or_404(UnifiedOrder, pk=order_id, is_deleted=False)
    cat = _get_cat(request) or order.category

    # --- 헤더 업데이트 ---
    try:
        vendor = Vendor.objects.get(pk=int(request.POST.get("vendor_id")))
        order_date = datetime.strptime(
            (request.POST.get("order_date") or order.order_date.strftime("%Y-%m-%d")), "%Y-%m-%d"
        ).date()
    except Exception as e:
        return HttpResponseBadRequest(f"Invalid header: {e}")

    order.vendor = vendor
    order.order_date = order_date
    if hasattr(order, "remark"):
        order.remark = (request.POST.get("header_remark") or "").strip()
    order.category = cat  # 탭 이동 가능하게 허용 (원치 않으면 제거)
    if hasattr(order, "updated_by"):
        order.updated_by = request.user
    order.save()

    # --- 아이템 재작성(간단·안전한 전략: 싹 지우고 다시 생성) ---
    UnifiedOrderItem.objects.filter(order=order).delete()

    item_apps   = request.POST.getlist("item_app[]")
    item_models = request.POST.getlist("item_model[]")
    item_ids    = request.POST.getlist("item_id[]")
    qtys        = request.POST.getlist("qty[]")
    unit_prices = request.POST.getlist("unit_price[]")
    exps        = request.POST.getlist("expected_date[]")
    iremarks    = request.POST.getlist("item_remark[]")

    rows = zip_longest(item_apps, item_models, item_ids, qtys, unit_prices, exps, iremarks, fillvalue="")

    created_cnt = 0
    for app, model, iid, qty, up, exp, irem in rows:
        app = (app or "").strip().lower()
        model = (model or "").strip().lower()
        if not (app and model and iid and qty):
            continue
        try:
            ct  = ContentType.objects.get_by_natural_key(app, model)
            iid = int(iid)
            q   = int(qty)
            upf = float(up) if str(up).strip() != "" else _suggest_unit_price(cat, iid)
            exp_date = datetime.strptime(exp, "%Y-%m-%d").date() if exp else None

            obj = ct.get_object_for_this_type(pk=iid)
            name = (getattr(obj, "name", None) or getattr(obj, "item_name", None) or str(obj))[:200]
            spec = (getattr(obj, "spec", None) or getattr(obj, "spec_name", None) or "")[:200]
            amount = round(q * upf, 4)

            item_kwargs = dict(
                order=order, item_ct=ct, item_id=iid,
                qty=q, unit_price=upf, amount=amount,
                expected_date=exp_date,
                item_name_snapshot=name, spec_snapshot=spec,
            )
            if hasattr(UnifiedOrderItem, "remark"):
                item_kwargs["remark"] = (irem or "").strip()

            UnifiedOrderItem.objects.create(**item_kwargs)
            created_cnt += 1
        except Exception as e:
            messages.warning(request, f"아이템 행 스킵: {app}/{model}/{iid} - {e}")
            continue

    if created_cnt == 0:
        messages.error(request, "유효한 아이템이 없습니다. (변경사항 저장 안됨)")
        return redirect(f"{reverse('purchase:uni_order_edit', args=[order.id])}?cat={cat}")

    messages.success(request, f"[{cat}] 발주 수정 저장 완료 · LOT={order.order_lot} · 품목수={created_cnt}")
    return redirect(f"{reverse('purchase:uni_order_list')}?cat={cat}")
