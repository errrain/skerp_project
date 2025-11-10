# purchase/views/unified.py (refactored)
# 표준 라이브러리
from datetime import date, datetime, timedelta
from calendar import monthrange
from itertools import zip_longest
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_UP


# Django
from django.templatetags.static import static
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.paginator import Paginator
from django.db import connection, transaction
from django.db.models import (
    Exists, F, IntegerField, Max, Min, OuterRef, Q, Subquery, Sum,
)
from types import SimpleNamespace
from django.db.models.functions import Coalesce
from django.http import (
    HttpResponse, HttpResponseBadRequest, HttpResponseForbidden, JsonResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.module_loading import import_string
from django.views.decorators.http import require_http_methods
from django.test.utils import CaptureQueriesContext

# 로컬 앱
from master.models import Warehouse
from vendor.models import Vendor
from purchase.models import (
    CATEGORY_CHOICES,
    UnifiedIssue,
    UnifiedOrder,
    UnifiedOrderItem,
    UnifiedReceipt,
    UnifiedReturn,
    # 선택: 존재하는 경우에만 서브 LOT 지원
    UnifiedReceiptLine,
)


# 서비스 함수(없어도 ImportError 나지 않게 안전 로딩)
try:
    from purchase.services import (
        apply_usage_line as service_apply_usage_line,
        apply_usage_receipt as service_apply_usage_receipt,
    )
except Exception:
    service_apply_usage_line = None
    service_apply_usage_receipt = None

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
    """
    통합 입고 목록(발주 기준)
    - UnifiedOrderItem 기준으로 발주수량, 입고수량, 미입고 수량, 입고상태, 최근 LOT/사용상태 계산
    """
    cat = _get_cat(request)

    qs = (
        UnifiedOrderItem.objects
        .select_related("order", "order__vendor")
        .filter(order__category=cat, order__is_deleted=False)
    )

    # 벤더 계정이면 자기 업체만
    if not getattr(request.user, "is_internal", False):
        vendor_id = getattr(getattr(request.user, "vendor", None), "id", None)
        if not vendor_id:
            return HttpResponseForbidden("No vendor bound to user")
        qs = qs.filter(order__vendor_id=vendor_id)

    # ── 필터 ──
    vendor_kw = (request.GET.get("vendor") or "").strip()
    product_kw = (request.GET.get("product") or "").strip()
    od_from    = (request.GET.get("order_date_from") or "").strip()
    od_to      = (request.GET.get("order_date_to") or "").strip()
    ex_from    = (request.GET.get("expected_date_from") or "").strip()
    ex_to      = (request.GET.get("expected_date_to") or "").strip()

    if vendor_kw:
        qs = qs.filter(order__vendor__name__icontains=vendor_kw)
    if product_kw:
        qs = qs.filter(
            Q(item_name_snapshot__icontains=product_kw)
            | Q(spec_snapshot__icontains=product_kw)
        )
    if od_from:
        qs = qs.filter(order__order_date__gte=od_from)
    if od_to:
        qs = qs.filter(order__order_date__lte=od_to)
    if ex_from:
        qs = qs.filter(expected_date__gte=ex_from)
    if ex_to:
        qs = qs.filter(expected_date__lte=ex_to)

    qs = qs.order_by("-order__order_date", "-order_id", "id")

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get("page") or 1)

    items = list(page_obj.object_list)
    item_ids = [it.id for it in items]

    rec_info = {}
    last_map = {}

    if item_ids:
        # 입고 합계 + 마지막 헤더 id
        rec_qs = UnifiedReceipt.objects.filter(
            category=cat,
            is_deleted=False,
            extra__order_item_id__in=item_ids,
        )
        agg_rows = (
            rec_qs.values("extra__order_item_id")
            .annotate(
                total_qty=Sum("qty"),
                last_id=Max("id"),
            )
        )

        for row in agg_rows:
            item_id = row["extra__order_item_id"]
            rec_info[item_id] = {
                "total_qty": row["total_qty"] or 0,
                "last_id": row["last_id"],
            }

        last_ids = [info["last_id"] for info in rec_info.values() if info.get("last_id")]
        if last_ids:
            last_map = {
                r.id: r
                for r in UnifiedReceipt.objects.filter(id__in=last_ids)
            }

    # ── 각 행에 계산 결과 주입 ──
    for it in items:
        order_qty = it.qty or 0

        info = rec_info.get(it.id, {})
        rec_total = info.get("total_qty") or 0
        try:
            rec_total_int = int(rec_total)
        except (TypeError, ValueError):
            rec_total_int = 0

        remaining = order_qty - rec_total_int
        if remaining < 0:
            remaining = 0

        it.received_qty  = rec_total_int
        it.remaining_qty = remaining
        it.can_receive   = remaining > 0   # ★ 추가: 입고 가능 여부 플래그

        # 발주 기준 입고상태
        if rec_total_int <= 0:
            it.inbound_status = "미입고"
        elif rec_total_int < order_qty:
            it.inbound_status = "부분입고"
        else:
            it.inbound_status = "입고완료"

        # 마지막 헤더 LOT / 사용상태
        last = None
        last_id = info.get("last_id")
        if last_id:
            last = last_map.get(last_id)
        it.last_receipt_lot   = getattr(last, "receipt_lot", "")
        it.last_use_status    = getattr(last, "use_status", "")
        it.last_receipt_date  = getattr(last, "date", None)

    page_obj.object_list = items

    context = {
        "cat": cat,
        "page_obj": page_obj,
        "filter": request.GET,
    }
    return render(request, "purchase/unified/receipts/list.html", context)


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
    """
    통합 출고(이동) 목록
    - CHEM: 서브 LOT 단위(실제 UnifiedReceiptLine 존재)
    - NF/SUP: 헤더 LOT 단일 관리 → 서브라인이 없으면 헤더를 '가상 라인' 1개로 만들어 내려줌
    기본 현재창고:
      CHEM/NF -> sk_wh_6,  SUP -> sk_wh_3
    """
    cat = _get_cat(request)

    # 기간(최근 7일 기본)
    today = date.today()
    default_from = today - timedelta(days=7)
    raw_from = (request.GET.get("date_from") or "").strip()
    raw_to   = (request.GET.get("date_to") or "").strip()

    try:
        date_from = date.fromisoformat(raw_from) if raw_from else default_from
    except ValueError:
        date_from = default_from
    try:
        date_to = date.fromisoformat(raw_to) if raw_to else today
    except ValueError:
        date_to = today

    # 필터
    q          = (request.GET.get("q") or "").strip()
    wh_code_in = (request.GET.get("wh") or "").strip()
    use_status = (request.GET.get("use_status") or "").strip()
    allowed_status = {"미사용", "부분사용", "사용완료"}

    # 카테고리별 현재창고 기본값
    if cat in ("CHEM", "NF"):
        default_wh_code = "sk_wh_6"   # 도금 약품 창고
    elif cat == "SUP":
        default_wh_code = "sk_wh_3"   # 도금 C동창고
    else:
        default_wh_code = ""
    effective_wh = wh_code_in or default_wh_code

    # 헤더 조회
    header_qs = (
        UnifiedReceipt.objects
        .select_related("warehouse", "vendor")
        .filter(
            category=cat, is_active=True, is_deleted=False,
            date__gte=date_from, date__lte=date_to,
        )
        .order_by("-date", "-id")
    )
    # 외부사용자 벤더 제한
    if not getattr(request.user, "is_internal", False):
        vendor_id = getattr(getattr(request.user, "vendor", None), "id", None)
        header_qs = header_qs.filter(vendor_id=vendor_id) if vendor_id else header_qs.none()

    headers = list(header_qs)
    receipt_ids = [h.id for h in headers] or [0]

    # 서브라인 조회(있을 때)
    lines_by_receipt: dict[int, list[UnifiedReceiptLine]] = {}
    if receipt_ids:
        line_qs = (
            UnifiedReceiptLine.objects
            .select_related("warehouse", "receipt", "receipt__warehouse")
            .filter(receipt_id__in=receipt_ids)
            .order_by("sub_seq", "id")
        )
        # 현재창고 필터: 라인 창고가 있으면 그 창고, 없으면 헤더 창고
        if effective_wh:
            line_qs = line_qs.filter(
                Q(warehouse__warehouse_id=effective_wh) |
                Q(warehouse__isnull=True, receipt__warehouse__warehouse_id=effective_wh)
            )
        if use_status in allowed_status:
            line_qs = line_qs.filter(use_status=use_status)

        for ln in line_qs:
            lines_by_receipt.setdefault(ln.receipt_id, []).append(ln)

    # 화면 아이템 구성
    items = []
    q_lower = q.lower()
    for h in headers:
        h.product_display = h.item_name_snapshot or "-"
        sub_lines = lines_by_receipt.get(h.id)

        if cat == "CHEM":
            # 약품은 서브라인 반드시 있어야 출력
            if not sub_lines:
                continue
        else:
            # NF/SUP: 서브라인 없으면 헤더 기준으로 '가상 라인' 1개 생성
            if not sub_lines:
                # 헤더 창고가 현재창고와 다르면 스킵
                header_is_in_wh = (h.warehouse and h.warehouse.warehouse_id == effective_wh)
                if not header_is_in_wh:
                    continue
                # 가상 라인(템플릿 호환용). id=0 → 이동 버튼은 당장 비활성 쪽으로 처리됨(다음 단계에 header move 지원)
                pseudo = SimpleNamespace(
                    id=0,
                    sub_lot=h.receipt_lot,
                    qty=h.qty,
                    use_status="미사용",
                    warehouse=None,   # 템플릿에서 없으면 헤더창고를 표시
                )
                sub_lines = [pseudo]

        # 품명 검색
        if q and q_lower not in h.product_display.lower():
            continue

        h.sub_lines = sub_lines
        items.append(h)

    # 페이징
    paginator = Paginator(items, 20)
    page_obj = paginator.get_page(request.GET.get("page") or 1)

    # page 제외 쿼리스트링
    qd = request.GET.copy()
    qd.pop("page", None)
    querystring = qd.urlencode()

    # 창고 목록 + 목적지 기본값
    warehouses = list(Warehouse.objects.filter(is_deleted="N").order_by("warehouse_id"))
    DEFAULT_DEST_CODE = "sk_wh_9"
    default_dest_id = None
    for w in warehouses:
        if getattr(w, "warehouse_id", "") == DEFAULT_DEST_CODE:
            default_dest_id = w.id
            break
    if default_dest_id is None and warehouses:
        default_dest_id = warehouses[0].id

    context = {
        "cat": cat,
        "items": page_obj.object_list,
        "page_obj": page_obj,
        "querystring": querystring,
        "warehouses": warehouses,
        "default_dest_id": default_dest_id,
        "today": today,
        "filter": {
            "q": q,
            "date_from": date_from.isoformat() if date_from else "",
            "date_to": date_to.isoformat() if date_to else "",
            "wh": effective_wh,
            "use_status": use_status,
        },
        "selected_wh": effective_wh,
    }
    return render(request, "purchase/unified/issues/list.html", context)


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


@require_http_methods(["GET"])
def order_edit(request, order_id: int):
    """
    기존 발주 수정 폼 — form.html을 재사용하되 프리셋을 내려준다.
    """
    order = get_object_or_404(UnifiedOrder, pk=order_id, is_deleted=False)
    cat = order.category

    # 취소/확정 등 편집 불가 조건 차단(사출 UX와 동일)
    if order.order_status != "NEW" or getattr(order, "cancel_at", None):
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
            "remark": getattr(it, "remark", "") or "",
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


@require_http_methods(["POST"])
@login_required
@transaction.atomic
def order_update(request, order_id: int):
    """
    기존 발주 업데이트 — 간단/안전: 기존 아이템 전부 삭제 후 재생성.
    """
    order = get_object_or_404(UnifiedOrder, pk=order_id, is_deleted=False)
    cat = order.category
    if order.order_status != "NEW" or getattr(order, "cancel_at", None):
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
    order.updated_by = request.user if hasattr(order, "updated_by") else None
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
    - 금액 계산은 Decimal 기반으로 변경(혼합연산 오류 방지)
    """
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
            ct  = ContentType.objects.get_by_natural_key(app, model)
            iid = int(iid)
            q   = Decimal(str(qty))
            # 최신가 제안 포함
            upf = Decimal(str(up)) if str(up).strip() != "" else Decimal(str(_suggest_unit_price(cat, iid)))
            exp_date = datetime.strptime(exp, "%Y-%m-%d").date() if exp else None

            obj = ct.get_object_for_this_type(pk=iid)
            name = (getattr(obj, "name", None) or getattr(obj, "item_name", None) or str(obj))[:200]
            spec = (getattr(obj, "spec", None) or getattr(obj, "spec_name", None) or "")[:200]

            amount = (q * upf).quantize(Decimal("0.0001"))

            item_kwargs = dict(
                order=order, item_ct=ct, item_id=iid,
                qty=int(q), unit_price=float(upf), amount=amount,
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

    if getattr(order, "cancel_at", None):
        messages.info(request, "이미 취소된 발주입니다.")
        return redirect(f"{reverse('purchase:uni_order_list')}?cat={cat}")

    if order.order_status != "NEW":
        messages.warning(request, "진행중/완료된 발주는 취소할 수 없습니다.")
        return redirect(f"{reverse('purchase:uni_order_list')}?cat={cat}")

    code = _cancel_code()
    if code:
        order.order_status = code
    order.cancel_at = timezone.now()
    if hasattr(order, "cancel_by"):
        order.cancel_by = request.user
    order.save(update_fields=["order_status", "cancel_at", "cancel_by"] if hasattr(order, "cancel_by") else ["order_status", "cancel_at"])

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


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                            인쇄(발주서)                                   ║
# ╚══════════════════════════════════════════════════════════════════════════╝
@require_http_methods(["GET"])
def order_print(request, order_id):
    """
    통합 발주서 인쇄용 화면
    - '입고 요청일': order.due_date 없으면 아이템 expected_date(최소~최대)로 대체
    - 합계/부가세: Decimal 기반 계산
    - 본문 행수: 20행 고정(빈행 채움, 초과 시 자동 확장)
    """
    # 발주/아이템 조회
    order = get_object_or_404(
        UnifiedOrder.objects.select_related("vendor", "created_by"),
        pk=order_id,
    )
    items = order.items.all().order_by("id")
    item_count = items.count()

    # 입고요청일 텍스트 계산
    dates = items.aggregate(min_date=Min("expected_date"), max_date=Max("expected_date"))
    if order.due_date:
        due_text = order.due_date.strftime("%Y년 %m월 %d일")
    else:
        dmin, dmax = dates["min_date"], dates["max_date"]
        if dmin and dmax:
            if dmin == dmax:
                due_text = dmin.strftime("%Y년 %m월 %d일")
            else:
                due_text = f"{dmin.strftime('%Y년 %m월 %d일')} ~ {dmax.strftime('%Y년 %m월 %d일')}"
        else:
            due_text = "-"

    # 합계 (Decimal 기반)
    totals = items.aggregate(total_qty=Sum("qty"), total_amount=Sum("amount"))
    total_qty = totals["total_qty"] or 0
    total_amount = totals["total_amount"] or Decimal("0")

    # 부가세/총액 (모두 Decimal로 계산)
    VAT_RATE = Decimal("0.10")
    vat_amount = (total_amount * VAT_RATE).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    total_amount_vat = (total_amount + vat_amount).quantize(Decimal("1"), rounding=ROUND_HALF_UP)

    # 행수: 최소 20행, 초과 시 아이템 수만큼
    base_rows = 20
    target_rows = max(base_rows, item_count)
    filler_range = range(target_rows - item_count)

    ctx = {
        "order": order,
        "items": items,
        "due_text": due_text,
        "total_qty": total_qty,
        "total_amount": total_amount,
        "total_amount_vat": total_amount_vat,
        # 회사 정보(없으면 템플릿 기본값 사용)
        "company_tel": "(062) 716-8264",
        "company_fax": "(062) 716-8267",
        "company_logo_url": static("purchase/img/seokyung_logo.png"),
        # 현재 시각: USE_TZ 여부와 무관하게 안전
        "now": timezone.now(),
        "page_no": 1,
        "filler_range": filler_range,
    }
    return render(request, "purchase/unified/orders/print.html", ctx)


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║               사용 처리 엔드포인트(CHEM 라인 / NF·SUP 헤더)               ║
# ╚══════════════════════════════════════════════════════════════════════════╝
@require_http_methods(["POST"])
@login_required
@transaction.atomic
def usage_line_apply(request):
    """
    CHEM: 서브 LOT 라인 단위 사용/반납/조정 처리
    body(JSON):
      - line_id: int
      - action: "use" | "return" | "adjust"
      - qty: Decimal-compatible string (use/return일 때 필수, adjust는 +/- 모두 허용)
      - occurred_at: "YYYY-MM-DD" (optional; 없으면 today)
      - remark, ref_type, ref_id (optional)
    """
    if service_apply_usage_line is None or UnifiedReceiptLine is None:
        return JsonResponse({"ok": False, "msg": "서비스 또는 모델이 준비되지 않았습니다."}, status=500)

    import json
    try:
        payload = json.loads(request.body.decode("utf-8"))
        line_id = int(payload.get("line_id"))
        action  = (payload.get("action") or "").strip().lower()  # use/return/adjust
        qty_raw = payload.get("qty")
        qty     = Decimal(str(qty_raw)) if qty_raw not in (None, "") else None
        occurred_at = (payload.get("occurred_at") or date.today().isoformat())
        remark  = (payload.get("remark") or "").strip()
        ref_type = (payload.get("ref_type") or "").strip() or None
        ref_id   = payload.get("ref_id")
        ref_id   = int(ref_id) if ref_id not in (None, "") else None
    except Exception as e:
        return JsonResponse({"ok": False, "msg": f"잘못된 요청: {e}"}, status=400)

    line = get_object_or_404(UnifiedReceiptLine, pk=line_id, receipt__is_deleted=False)

    # 권한: 외부 사용자는 자기 벤더 것만
    if not _ensure_vendor_scope(request.user, line.receipt.vendor_id):
        return JsonResponse({"ok": False, "msg": "권한 없음"}, status=403)

    try:
        res = service_apply_usage_line(
            user=request.user,
            line=line,
            action=action,
            qty=qty,
            occurred_at=occurred_at,
            remark=remark,
            ref_type=ref_type, ref_id=ref_id,
        )
        # 서비스가 헤더 동기화까지 수행한다고 가정
        data = {
            "ok": True,
            "line_id": line.id,
            "receipt_id": line.receipt_id,
            "new_line_use_status": getattr(line, "use_status", None),
            "new_receipt_use_status": getattr(line.receipt, "use_status", None),
            "used_qty": str(getattr(line, "used_qty", "")),
        }
        data.update(res if isinstance(res, dict) else {})
        return JsonResponse(data)
    except Exception as e:
        return JsonResponse({"ok": False, "msg": str(e)}, status=400)


@require_http_methods(["POST"])
@login_required
@transaction.atomic
def usage_receipt_apply(request):
    """
    NF/SUP: 헤더 단위 사용/반납/조정 처리
    body(JSON):
      - receipt_id: int
      - action: "use" | "return" | "adjust"
      - qty: Decimal-compatible string
      - occurred_at: "YYYY-MM-DD" (optional)
      - remark, ref_type, ref_id (optional)
    """
    if service_apply_usage_receipt is None:
        return JsonResponse({"ok": False, "msg": "서비스가 준비되지 않았습니다."}, status=500)

    import json
    try:
        payload = json.loads(request.body.decode("utf-8"))
        receipt_id = int(payload.get("receipt_id"))
        action  = (payload.get("action") or "").strip().lower()
        qty     = Decimal(str(payload.get("qty")))
        occurred_at = (payload.get("occurred_at") or date.today().isoformat())
        remark  = (payload.get("remark") or "").strip()
        ref_type = (payload.get("ref_type") or "").strip() or None
        ref_id   = payload.get("ref_id")
        ref_id   = int(ref_id) if ref_id not in (None, "") else None
    except Exception as e:
        return JsonResponse({"ok": False, "msg": f"잘못된 요청: {e}"}, status=400)

    receipt = get_object_or_404(UnifiedReceipt, pk=receipt_id, is_deleted=False)

    # 권한: 외부 사용자는 자기 벤더 것만
    if not _ensure_vendor_scope(request.user, receipt.vendor_id):
        return JsonResponse({"ok": False, "msg": "권한 없음"}, status=403)

    try:
        res = service_apply_usage_receipt(
            user=request.user,
            receipt=receipt,
            action=action,
            qty=qty,
            occurred_at=occurred_at,
            remark=remark,
            ref_type=ref_type, ref_id=ref_id,
        )
        data = {
            "ok": True,
            "receipt_id": receipt.id,
            "new_receipt_use_status": getattr(receipt, "use_status", None),
            "used_qty": str(getattr(receipt, "used_qty", "")),
        }
        data.update(res if isinstance(res, dict) else {})
        return JsonResponse(data)
    except Exception as e:
        return JsonResponse({"ok": False, "msg": str(e)}, status=400)

def _next_unified_receipt_lot(d: date) -> str:
    """
    통합 입고 헤더 LOT 생성:
    IN + YYYYMMDD + 3자리(001, 002, ...)
    """
    prefix = d.strftime("IN%Y%m%d")
    last = (
        UnifiedReceipt.objects
        .filter(receipt_lot__startswith=prefix)
        .order_by("-id")
        .values_list("receipt_lot", flat=True)
        .first()
    )
    if last and len(last) > len(prefix) and last[len(prefix):].isdigit():
        seq = int(last[len(prefix):]) + 1
    else:
        seq = 1
    return f"{prefix}{seq:03d}"

QTY_Q = Decimal("0.001")  # Decimal(18,3) 정책

def _to_dec(v) -> Decimal:
    try:
        d = Decimal(str(v or "0")).quantize(QTY_Q, rounding=ROUND_DOWN)
        return d if d >= 0 else Decimal("0")
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


@require_http_methods(["GET"])
@login_required
@require_http_methods(["GET"])
def receipt_candidates(request, order_id: int):
    """
    통합 입고 후보 화면 (CHEM / NF / SUP 공용)

    1) 발주수량 / 이미 입고된 수량 / 미입고 수량 계산
    2) 카테고리별 기본 창고(default_wh_id) 결정
    3) 약품(CHEM)이면 단위규격(chemical.unit_qty) 가져오기
    4) 동일 품목의 기존 입고 이력(헤더 + 서브 LOT) 조회
    """

    # 1) 주문 + 벤더 권한 체크
    order = get_object_or_404(
        UnifiedOrder.objects.select_related("vendor"),
        pk=order_id,
        is_deleted=False,
    )
    vendor = order.vendor

    if not _ensure_vendor_scope(request.user, vendor.id):
        return HttpResponseForbidden("이 발주에 접근 권한이 없습니다.")

    # 카테고리(CHEM / NF / SUP)
    cat = (request.GET.get("cat") or order.category or "").upper()

    # 2) 발주 품목 찾기(item_id 필수)
    try:
        item_id = int(request.GET.get("item_id") or 0)
    except ValueError:
        item_id = 0

    order_item = get_object_or_404(
        UnifiedOrderItem.objects.select_related("order"),
        pk=item_id,
        order=order,
    )

    # 3) 발주수량 / 입고수량 / 미입고수량 계산
    ordered_qty = _to_dec(order_item.qty)

    agg = (
        UnifiedReceipt.objects
        .filter(
            category=cat,
            vendor_id=vendor.id,
            item_ct=order_item.item_ct,
            item_id=order_item.item_id,
            is_deleted=False,
        )
        .aggregate(total=Sum("qty"))
    )
    received_qty = _to_dec(agg["total"] or Decimal("0"))
    remaining_qty = ordered_qty - received_qty
    if remaining_qty < 0:
        remaining_qty = Decimal("0")

    # 더 이상 입고 가능 여부 (미입고 0이면 False)
    can_receive = remaining_qty > Decimal("0")

    # 4) 창고 / 기본창고 결정
    warehouses = list(Warehouse.objects.all().order_by("name"))

    default_wh_code = None
    if cat in ("CHEM", "NF"):
        default_wh_code = "sk_wh_6"   # 도금 약품 창고
    elif cat == "SUP":
        default_wh_code = "sk_wh_3"   # 부자재 창고

    default_wh_id = None
    if default_wh_code:
        for w in warehouses:
            if getattr(w, "warehouse_id", None) == default_wh_code:
                default_wh_id = w.id
                break

    # 5) CHEM 인 경우 단위 규격(약품 속성 unit_qty) 가져오기
    chem_unit_qty = None
    if cat == "CHEM":
        try:
            chem = order_item.item  # GenericForeignKey
            chem_unit_qty = getattr(chem, "unit_qty", None)
        except Exception:
            chem_unit_qty = None

    # 6) 기존 입고 이력(헤더 + 서브 LOT) 조회
    existing_receipts = (
        UnifiedReceipt.objects
        .filter(
            category=cat,
            vendor_id=vendor.id,
            item_ct=order_item.item_ct,
            item_id=order_item.item_id,
            is_deleted=False,
        )
        .select_related("warehouse")
        .prefetch_related("lines")
        .order_by("date", "id")
    )

    # 성적서 파일이 있는 가장 최근 헤더 1건 (후보 화면 상단에서 링크로 사용)
    cert_receipt = (
        existing_receipts
        .filter(certificate_file__isnull=False)
        .exclude(certificate_file="")
        .order_by("-date", "-id")
        .first()
    )

    # 7) 신규 헤더 LOT 제안 (INYYYYMMDD-*** 형식)
    today = date.today()
    header_lot = get_next_lot("IN", today)

    # 8) 템플릿 컨텍스트
    ctx = {
        "cat": cat,
        "order": order,
        "item": order_item,
        "vendor": vendor,
        "ordered_qty": ordered_qty,
        "received_qty": received_qty,
        "remaining_qty": remaining_qty,
        "can_receive": can_receive,
        "header_lot": header_lot,
        "today": today,
        # 창고 관련
        "warehouses": warehouses,
        "default_wh_id": default_wh_id,
        # 카테고리 플래그
        "is_chem": cat == "CHEM",
        "is_nf":   cat == "NF",
        "is_sup":  cat == "SUP",
        "chem_unit_qty": chem_unit_qty,
        # 기존 입고 이력 / 성적서 헤더
        "existing_receipts": existing_receipts,
        "cert_receipt": cert_receipt,
    }
    return render(request, "purchase/unified/receipts/candidates.html", ctx)

@require_http_methods(["POST"])
@login_required
@transaction.atomic
def receipt_commit(request, order_id: int):
    """
    통합 입고 확정
    - CHEM : 헤더 + 서브 LOT N (라인 생성)
    - NF/SUP : 헤더만 생성
    """
    user = request.user

    # ----- 공통 입력값 -----
    order = get_object_or_404(
        UnifiedOrder.objects.select_related("vendor"),
        pk=order_id,
        is_deleted=False,
    )

    # 벤더 권한 체크
    if not _ensure_vendor_scope(user, order.vendor_id):
        return HttpResponseForbidden("이 발주건에 대한 접근 권한이 없습니다.")

    cat = (request.GET.get("cat") or request.POST.get("cat") or order.category or "").upper()

    # 품목(발주 아이템)
    try:
        item_id = int(request.POST.get("item_id") or "0")
    except ValueError:
        messages.error(request, "유효하지 않은 item_id 입니다.")
        return redirect("purchase:uni_receipt_candidates", order_id=order_id)

    item = get_object_or_404(
        UnifiedOrderItem.objects.select_related("order"),
        pk=item_id,
        order=order,
    )

    # 입고일
    raw_date = request.POST.get("receipt_date")
    if raw_date:
        try:
            receipt_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
        except Exception:
            receipt_date = date.today()
    else:
        receipt_date = date.today()

    header_lot = (request.POST.get("header_lot") or "").strip()
    if not header_lot:
        messages.error(request, "헤더 LOT 는 필수입니다.")
        return redirect("purchase:uni_receipt_candidates", order_id=order_id)

    remark = (request.POST.get("remark") or "").strip()

    # 기본 창고
    default_wh = None
    default_wh_id = request.POST.get("default_wh_id")
    if default_wh_id:
        default_wh = Warehouse.objects.filter(id=default_wh_id).first()
    if default_wh is None:
        messages.error(request, "기본 창고를 선택해 주세요.")
        return redirect("purchase:uni_receipt_candidates", order_id=order_id)

    # 성적서 파일(NF 필수, CHEM 선택)
    certificate_file = request.FILES.get("certificate_file")

    # 미입고 수량 (뷰에서 hidden 으로 내려준 값, 없으면 발주수량 사용)
    remaining_qty = _to_dec(request.POST.get("remaining_qty") or item.qty)

    # ★ 미입고가 0 이하면 공통 차단
    if remaining_qty <= Decimal("0"):
        messages.error(request, "미입고 수량이 없습니다. 추가 입고를 할 수 없습니다.")
        return redirect("purchase:uni_receipt_candidates", order_id=order_id)

    created_receipt = None
    created_lines = 0

    # ------------------------------------------------------------------
    # 1) 약품(CHEM) : 헤더 + 서브 LOT 라인 생성
    # ------------------------------------------------------------------
    if cat == "CHEM":
        sub_lots    = request.POST.getlist("sub_lot[]")
        sub_qtys    = request.POST.getlist("sub_qty[]")
        sub_wh_ids  = request.POST.getlist("sub_wh_id[]")
        sub_expires = request.POST.getlist("sub_expire[]")
        sub_remarks = request.POST.getlist("sub_remark[]")

        rows: list[dict] = []
        total_qty = Decimal("0")

        for idx, lot in enumerate(sub_lots):
            lot = (lot or "").strip()
            qty = _to_dec(sub_qtys[idx] if idx < len(sub_qtys) else "")
            if qty <= 0:
                continue

            wh = default_wh
            if idx < len(sub_wh_ids) and sub_wh_ids[idx]:
                wh = Warehouse.objects.filter(id=sub_wh_ids[idx]).first() or default_wh

            expire_raw = (sub_expires[idx] if idx < len(sub_expires) else "") or ""
            line_remark = (sub_remarks[idx] if idx < len(sub_remarks) else "").strip()

            # ★ 유효기간 문자열 → DateField
            expiry_date = None
            if expire_raw.strip():
                try:
                    expiry_date = date.fromisoformat(expire_raw.strip())
                except ValueError:
                    expiry_date = None

            if not lot:
                lot = f"{header_lot}-{idx+1}"

            rows.append(
                {
                    "lot": lot,
                    "qty": qty,
                    "warehouse": wh,
                    "expiry_date": expiry_date,
                    "remark": line_remark,
                }
            )
            total_qty += qty

        if not rows:
            messages.error(request, "서브 LOT 수량이 없습니다.")
            return redirect("purchase:uni_receipt_candidates", order_id=order_id)

        if remaining_qty > Decimal("0") and total_qty > remaining_qty:
            messages.error(request, "서브 LOT 합계가 미입고 수량을 초과합니다.")
            return redirect("purchase:uni_receipt_candidates", order_id=order_id)

        # 헤더 수량은 정수 필드이므로 내림
        header_qty_int = int(total_qty.to_integral_value(rounding=ROUND_DOWN))

        # order / order_item 은 JSON 으로만 남김
        extra = {
            "order_id": order.id,
            "order_item_id": item.id,
            "order_lot": order.order_lot,
            "category": cat,
        }

        created_receipt = UnifiedReceipt.objects.create(
            receipt_lot=header_lot,
            date=receipt_date,
            qty=header_qty_int,
            remark=remark,
            created_by=user,
            category=cat,
            vendor=order.vendor,
            item_ct=item.item_ct,
            item_id=item.item_id,
            warehouse=default_wh,
            used_qty=Decimal("0"),
            use_status="미사용",
            item_name_snapshot=item.item_name_snapshot,
            spec_snapshot=item.spec_snapshot,
            extra=extra,
            certificate_file=certificate_file or None,
            is_used=False,
        )

        # 서브 LOT 라인 생성 (★ 비고 자동 조작 없음)
        for seq, r in enumerate(rows, start=1):
            UnifiedReceiptLine.objects.create(
                receipt=created_receipt,
                sub_seq=seq,
                sub_lot=r["lot"],
                qty=r["qty"],
                used_qty=Decimal("0"),
                use_status="미사용",
                warehouse=r["warehouse"],
                expiry_date=r["expiry_date"],
                remark=r["remark"],
            )
            created_lines += 1

    # ------------------------------------------------------------------
    # 2) 비철 / 부자재 : 헤더만 생성
    # ------------------------------------------------------------------
    elif cat in ("NF", "SUP"):
        # 템플릿에서 어떤 이름을 쓰든 여기서 하나라도 들어오면 사용
        qty_dec = _to_dec(
            request.POST.get("header_qty")
            or request.POST.get("nf_qty")
            or request.POST.get("sup_qty")
        )
        if qty_dec <= 0:
            messages.error(request, "입고 수량을 입력해 주세요.")
            return redirect("purchase:uni_receipt_candidates", order_id=order_id)

        if qty_dec > remaining_qty:
            messages.error(request, "입고 수량이 미입고 수량을 초과합니다.")
            return redirect("purchase:uni_receipt_candidates", order_id=order_id)

        # ★ NF 전용: 성적서 / 창고 / 비고
        if cat == "NF":
            if not certificate_file:
                messages.error(request, "비철 입고는 성적서 파일 업로드가 필요합니다.")
                return redirect("purchase:uni_receipt_candidates", order_id=order_id)

            nf_wh_id = request.POST.get("nf_wh_id")
            if nf_wh_id:
                nf_wh = Warehouse.objects.filter(id=nf_wh_id).first()
                if nf_wh:
                    default_wh = nf_wh

            nf_remark = (request.POST.get("nf_remark") or "").strip()
            if nf_remark:
                if remark:
                    remark += " "
                remark += nf_remark

        # ★ SUP 전용: 수량 확인 체크박스 / 비고
        elif cat == "SUP":
            sup_flag = (request.POST.get("sup_confirm") or "").strip().lower()
            if sup_flag not in ("y", "on", "1", "true"):
                messages.error(request, "부자재 입고 수량 확인 체크박스를 선택해 주세요.")
                return redirect("purchase:uni_receipt_candidates", order_id=order_id)

            sup_remark = (request.POST.get("sup_remark") or "").strip()
            if sup_remark:
                if remark:
                    remark += " "
                remark += sup_remark

        header_qty_int = int(qty_dec.to_integral_value(rounding=ROUND_DOWN))

        extra = {
            "order_id": order.id,
            "order_item_id": item.id,
            "order_lot": order.order_lot,
            "category": cat,
        }

        created_receipt = UnifiedReceipt.objects.create(
            receipt_lot=header_lot,
            date=receipt_date,
            qty=header_qty_int,
            remark=remark,
            created_by=user,
            category=cat,
            vendor=order.vendor,
            item_ct=item.item_ct,
            item_id=item.item_id,
            warehouse=default_wh,
            used_qty=Decimal("0"),
            use_status="미사용",
            item_name_snapshot=item.item_name_snapshot,
            spec_snapshot=item.spec_snapshot,
            extra=extra,
            certificate_file=certificate_file if cat == "NF" else None,
            is_used=False,
        )

    else:
        messages.error(request, f"지원되지 않는 카테고리입니다: {cat}")
        return redirect("purchase:uni_receipt_candidates", order_id=order_id)

    # ------------------------------------------------------------------
    # 완료 메시지 & 이동
    # ------------------------------------------------------------------
    if not created_receipt:
        messages.error(request, "생성된 입고가 없습니다.")
    else:
        msg = f"입고 완료 · 헤더 LOT {created_receipt.receipt_lot}"
        if created_lines:
            msg += f" · 서브 LOT {created_lines}건"
        messages.success(request, msg)

    return redirect(f"{reverse('purchase:uni_receipt_list')}?cat={cat}")

@require_http_methods(["GET", "POST"])
@login_required
def receipt_line_edit(request, line_id: int):
    """
    CHEM 서브 LOT( UnifiedReceiptLine ) 단건 수정 화면.

    - 헤더: 입고일(date), 창고(warehouse), 성적서 파일(certificate_file)
    - 라인: 유효기간(expiry_date), 비고(remark)
    """
    line = get_object_or_404(
        UnifiedReceiptLine.objects.select_related("receipt", "receipt__vendor", "receipt__warehouse"),
        pk=line_id,
    )
    receipt = line.receipt

    # 벤더 권한 체크
    if not _ensure_vendor_scope(request.user, receipt.vendor_id):
        return HttpResponseForbidden("이 입고 건에 대한 접근 권한이 없습니다.")

    cat = (receipt.category or "").upper()
    extra = receipt.extra or {}
    order_id = extra.get("order_id")
    order_item_id = extra.get("order_item_id")
    order_lot = extra.get("order_lot")

    # 돌아가기 URL
    if order_id and order_item_id:
        back_url = (
            f"{reverse('purchase:uni_receipt_candidates', kwargs={'order_id': order_id})}"
            f"?item_id={order_item_id}&cat={cat}"
        )
    else:
        back_url = f"{reverse('purchase:uni_receipt_list')}?cat={cat}"

    warehouses = Warehouse.objects.all().order_by("name")

    if request.method == "POST":
        receipt_date_raw = (request.POST.get("receipt_date") or "").strip()
        expiry_raw = (request.POST.get("expiry_date") or "").strip()
        remark_raw = (request.POST.get("remark") or "").strip()
        receipt_wh_id = (request.POST.get("receipt_wh_id") or "").strip()

        error = False

        # 입고일 파싱
        if receipt_date_raw:
            try:
                receipt_date = date.fromisoformat(receipt_date_raw)
            except ValueError:
                messages.error(request, "입고일 형식이 올바르지 않습니다. (YYYY-MM-DD)")
                receipt_date = receipt.date
                error = True
        else:
            receipt_date = receipt.date

        # 유효기간 파싱
        if expiry_raw:
            try:
                expiry_date = date.fromisoformat(expiry_raw)
            except ValueError:
                messages.error(request, "유효기간 형식이 올바르지 않습니다. (YYYY-MM-DD)")
                expiry_date = line.expiry_date
                error = True
        else:
            expiry_date = None

        # 헤더 창고
        new_receipt_wh = receipt.warehouse
        if receipt_wh_id:
            try:
                new_receipt_wh = Warehouse.objects.get(id=int(receipt_wh_id))
            except (Warehouse.DoesNotExist, ValueError):
                messages.error(request, "창고 선택값이 올바르지 않습니다.")
                error = True

        # 성적서 파일 처리
        delete_cert = (request.POST.get("delete_certificate") or "").strip().lower() in ("y", "on", "1", "true")
        new_cert = request.FILES.get("certificate_file")

        if error:
            ctx = {
                "cat": cat,
                "receipt": receipt,
                "line": line,
                "order_lot": order_lot,
                "item_name": receipt.item_name_snapshot,
                "spec": receipt.spec_snapshot,
                "receipt_date_raw": receipt_date_raw or (receipt.date.isoformat() if receipt.date else ""),
                "receipt_wh_id": int(receipt_wh_id or (receipt.warehouse_id or 0)),
                "expiry_raw": expiry_raw,
                "remark_raw": remark_raw,
                "warehouses": warehouses,
                "back_url": back_url,
            }
            return render(request, "purchase/unified/receipts/line_edit.html", ctx)

        # 실제 저장
        receipt.date = receipt_date
        receipt.warehouse = new_receipt_wh

        if delete_cert:
            if receipt.certificate_file:
                receipt.certificate_file.delete(save=False)
            receipt.certificate_file = None
        elif new_cert:
            receipt.certificate_file = new_cert

        receipt.save()

        line.expiry_date = expiry_date
        line.remark = remark_raw
        line.save()

        messages.success(request, f"서브 LOT {line.sub_lot} 정보가 수정되었습니다.")
        return redirect(back_url)

    # GET 초기값
    ctx = {
        "cat": cat,
        "receipt": receipt,
        "line": line,
        "order_lot": order_lot,
        "item_name": receipt.item_name_snapshot,
        "spec": receipt.spec_snapshot,
        "receipt_date_raw": receipt.date.isoformat() if receipt.date else "",
        "receipt_wh_id": receipt.warehouse_id,
        "expiry_raw": line.expiry_date.isoformat() if line.expiry_date else "",
        "remark_raw": line.remark or "",
        "warehouses": warehouses,
        "back_url": back_url,
    }
    return render(request, "purchase/unified/receipts/line_edit.html", ctx)