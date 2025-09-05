# purchase/views/injection.py
from datetime import date, datetime
import json
import logging

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Sum, OuterRef, Subquery, Case, When, Value, CharField
from django.db.models.functions import TruncDate
from django.http import JsonResponse, HttpResponseForbidden, HttpResponseBadRequest
from django.shortcuts import render, redirect
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from injectionorder.models import InjectionOrder
from master.models import Warehouse
from purchase.models import InjectionReceipt, InjectionIssue
from quality.inspections.models import IncomingInspection, QCStatus
from django.conf import settings

logger = logging.getLogger(__name__)

# ────────────────────────────────
# Subquery 정의 (최신 검사 상태/일시, 최신 입고 LOT)
# ────────────────────────────────
_latest_insp_status = (
    IncomingInspection.objects
    .filter(order=OuterRef("pk"))
    .order_by("-created_at", "-id")
    .values("status")[:1]
)
_latest_insp_date = (
    IncomingInspection.objects
    .filter(order=OuterRef("pk"))
    .order_by("-created_at", "-id")
    .values("inspection_date")[:1]
)
_latest_receipt_lot = (
    InjectionReceipt.objects
    .filter(order=OuterRef("pk"))
    .order_by("-created_at", "-id")
    .values("receipt_lot")[:1]
)

# -------------------------------
# 유틸
# -------------------------------
DEFAULT_WH_ID = "sk_wh_5"  # 옥상창고

def _get_default_wh():
    """기본 창고(sk_wh_5) – is_deleted 타입과 무관하게 안전 조회"""
    return Warehouse.objects.filter(warehouse_id=DEFAULT_WH_ID).first()

def _make_receipt_lot(model_cls, d: date) -> str:
    """IN + YYYYMMDD + NN 형식 LOT 번호 생성"""
    base = d.strftime("IN%Y%m%d")
    cnt = model_cls.objects.filter(receipt_lot__startswith=base).count()
    return f"{base}{cnt + 1:02d}"

def _parse_payload(request):
    """
    JSON 우선 → form-encoded(request.POST) → querystring 스타일 순으로 파싱.
    요청 Content-Type/본문 스니펫을 DEBUG 로깅.
    """
    from urllib.parse import parse_qs

    ctype = request.META.get("CONTENT_TYPE", "")
    raw = request.body or b""
    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception:
        text = str(raw)

    logger.debug("REQ ctype=%s len=%s body[:200]=%r", ctype, len(raw), text[:200])

    if "application/json" in ctype:
        try:
            return json.loads(text)
        except Exception as e:
            logger.warning("JSON parse error: %s; body=%r", e, text)

    if request.POST:
        data = request.POST.dict()
        logger.debug("Using request.POST fallback: %s", data)
        return data

    if text:
        try:
            qd = {k: (v[0] if isinstance(v, list) else v)
                  for k, v in parse_qs(text).items()}
            logger.debug("Using parse_qs fallback: %s", qd)
            return qd
        except Exception as e:
            logger.warning("parse_qs error: %s", e)

    return {}

def _today_local():
    """
    오늘 날짜를 안전하게 반환.
    - USE_TZ=True: timezone.localdate()
    - USE_TZ=False: date.today() (localtime() 오류 회피)
    """
    try:
        if getattr(settings, "USE_TZ", False):
            return timezone.localdate()
        return date.today()
    except Exception as e:
        logger.debug("today fallback due to %s", e)
        return date.today()


def _parse_move_date(s: str):
    if not s:
        d = _today_local()
        logger.debug("_parse_move_date: empty -> today=%s", d)
        return d
    try:
        d = datetime.strptime(s, "%Y-%m-%d").date()
        logger.debug("_parse_move_date: parsed=%s", d)
        return d
    except Exception as e:
        d = _today_local()
        logger.warning("_parse_move_date: invalid %r (%s) -> today=%s", s, e, d)
        return d

def _make_issue_lot(receipt_id: int, move_date: date) -> str:
    """IS + YYYYMMDD + receipt_id(6)"""
    return f"IS{move_date.strftime('%Y%m%d')}{receipt_id:06d}"

# ────────────────────────────────
# 입고 목록
# ────────────────────────────────
@require_http_methods(["GET"])
def receipt_list(request):
    """
    사출 입고 목록:
    - 대상: '입고대기' + '입고완료'
    - 표시: 수량합, 발주/배송/검사 최신, 최신 입고 LOT
    - 검색: 발주처, 품명, 발주일 범위, 검사일 범위, 상태
    - 페이징: 20개
    """
    qs = (
        InjectionOrder.objects
        .filter(status__in=["입고대기", "입고완료"])
        .select_related("vendor")
        .prefetch_related("items")
        .annotate(
            qty_sum=Sum("items__quantity"),
            latest_insp_status=Subquery(_latest_insp_status),
            latest_insp_date=Subquery(_latest_insp_date),
            latest_receipt_lot=Subquery(_latest_receipt_lot),
            shipping_date=TruncDate("shipping_registered_at"),
            insp_status_display=Case(
                When(latest_insp_status__in=[QCStatus.PASS, "합격"], then=Value("합격")),
                When(latest_insp_status__in=[QCStatus.FAIL, "불합격"], then=Value("불합격")),
                When(latest_insp_status__in=[QCStatus.HOLD, "보류"], then=Value("보류")),
                When(latest_insp_status__in=[QCStatus.DRAFT, "대기"], then=Value("대기")),
                default=Value("-"),
                output_field=CharField(),
            ),
        )
        .order_by("-latest_insp_date", "-id")
    )

    # 검색 파라미터
    vendor         = request.GET.get("vendor")
    product        = request.GET.get("product")
    order_date_from= request.GET.get("order_date_from")
    order_date_to  = request.GET.get("order_date_to")
    insp_date_from = request.GET.get("insp_date_from")
    insp_date_to   = request.GET.get("insp_date_to")
    status         = request.GET.get("status")

    if vendor:
        qs = qs.filter(vendor__name__icontains=vendor)
    if product:
        qs = qs.filter(items__injection__name__icontains=product)
    if order_date_from:
        qs = qs.filter(order_date__gte=order_date_from)
    if order_date_to:
        qs = qs.filter(order_date__lte=order_date_to)
    if insp_date_from:
        qs = qs.filter(latest_insp_date__gte=insp_date_from)
    if insp_date_to:
        qs = qs.filter(latest_insp_date__lte=insp_date_to)
    if status:
        qs = qs.filter(status=status)

    paginator = Paginator(qs, 20)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    logger.debug(
        "[receipt_list] vendor=%s product=%s order_date=(%s~%s) insp_date=(%s~%s) "
        "status=%s page=%s count=%s",
        vendor, product, order_date_from, order_date_to, insp_date_from, insp_date_to,
        status, page_number, qs.count()
    )

    return render(request, "purchase/injection/receipts/list.html", {
        "page_obj": page_obj,
        "page_range": paginator.get_elided_page_range(number=page_obj.number),
        "today": date.today(),
        "filter": request.GET,  # 검색창 값 유지
    })

# ────────────────────────────────
# 입고 저장
# ────────────────────────────────
@require_http_methods(["POST"])
@transaction.atomic
def receipt_add(request, order_id: int | None = None):
    selected_ids = request.POST.getlist("selected_ids")
    if order_id and str(order_id) not in selected_ids:
        selected_ids.append(str(order_id))
    if not selected_ids:
        messages.warning(request, "선택된 행이 없습니다.")
        return redirect("purchase:inj_receipt_list")

    rec_date_str = request.POST.get("receipt_date") or date.today().strftime("%Y-%m-%d")
    try:
        rec_date = datetime.strptime(rec_date_str, "%Y-%m-%d").date()
    except ValueError:
        rec_date = date.today()

    wh = _get_default_wh()
    if not wh:
        messages.error(request, "기본 창고(sk_wh_5)를 찾을 수 없습니다.")
        return redirect("purchase:inj_receipt_list")

    orders = (
        InjectionOrder.objects
        .select_for_update()
        .select_related("vendor")
        .prefetch_related("items")
        .filter(pk__in=selected_ids, status="입고대기")
    )

    success = skipped = 0
    PASS_VALUES = {QCStatus.PASS, "합격"}

    for order in orders:
        latest = (
            IncomingInspection.objects
            .filter(order=order)
            .order_by("-created_at", "-id")
            .first()
        )
        if not latest or latest.status not in PASS_VALUES:
            skipped += 1
            continue

        qty_sum = order.items.aggregate(s=Sum("quantity"))["s"] or 0
        if qty_sum <= 0:
            skipped += 1
            continue

        remark = (request.POST.get(f"remark_{order.pk}", "") or "").strip()
        lot = _make_receipt_lot(InjectionReceipt, rec_date)

        try:
            InjectionReceipt.objects.create(
                order=order,
                warehouse=wh,
                receipt_lot=lot,
                date=rec_date,
                qty=qty_sum,
                remark=remark,
                created_by=request.user,
                is_active=True,
                is_deleted=False,
                order_lot_snapshot=order.order_lot,
            )
            order.status = "입고완료"
            order.save(update_fields=["status"])
            success += 1
        except Exception as e:
            logger.exception("입고 저장 실패 (order_id=%s, lot=%s) : %s", order.pk, lot, e)
            skipped += 1

    if success:
        messages.success(request, f"입고 완료 {success}건 (스킵 {skipped}건)")
    else:
        messages.warning(request, f"처리된 입고 건이 없습니다. (스킵 {skipped}건)")
    return redirect("purchase:inj_receipt_list")

# ────────────────────────────────
# 출고(이동) 목록
# ────────────────────────────────
@require_GET
def issue_list(request):
    """
    사출 출고(이동) 목록
    - 대상: 미사용(is_used=False) 입고 데이터
    - 기본 위치: 옥상창고(sk_wh_5)만; 위치 지정 시 해당 창고만
    - 검색: 품명(q, 파이썬단 필터), 입고일(date_from~date_to), 위치(wh)
    - 페이징: 20건
    """
    qs = (
        InjectionReceipt.objects
        .filter(is_active=True, is_deleted=False, is_used=False)
        .select_related("order", "warehouse")
        .order_by("-date", "-id")
    )

    # 검색 파라미터
    q         = (request.GET.get("q") or "").strip()
    date_from = (request.GET.get("date_from") or "").strip()
    date_to   = (request.GET.get("date_to") or "").strip()
    wh_code   = (request.GET.get("wh") or "").strip()

    if wh_code:
        qs = qs.filter(warehouse__warehouse_id=wh_code)
    else:
        qs = qs.filter(warehouse__warehouse_id=DEFAULT_WH_ID)

    if date_from:
        qs = qs.filter(date__gte=date_from)
    if date_to:
        qs = qs.filter(date__lte=date_to)

    # 이동 목적지용 창고 목록 + 기본값(생산현장 sk_wh_9)
    warehouses = list(Warehouse.objects.all().order_by("warehouse_id"))
    default_dest_id = next((w.id for w in warehouses if w.warehouse_id == "sk_wh_9"),
                           (warehouses[0].id if warehouses else None))

    # 품명 표시값 주입 + 품명 검색
    items = list(qs)
    q_lower = q.lower()
    filtered = []
    for r in items:
        name = "-"
        try:
            if hasattr(r.order, "items"):
                first_item = r.order.items.all().first()
                if first_item:
                    if getattr(getattr(first_item, "product", None), "name", None):
                        name = first_item.product.name
                    elif getattr(getattr(first_item, "injection", None), "name", None):
                        name = first_item.injection.name
                    elif getattr(first_item, "name", None):
                        name = first_item.name
            if name == "-":
                if getattr(getattr(r.order, "product", None), "name", None):
                    name = r.order.product.name
                elif getattr(r.order, "product_name", None):
                    name = r.order.product_name
                elif getattr(r.order, "item_name", None):
                    name = r.order.item_name
        except Exception:
            pass
        r.product_display = name or "-"

        if q:
            if (r.product_display or "").lower().find(q_lower) != -1:
                filtered.append(r)
        else:
            filtered.append(r)

    paginator = Paginator(filtered, 20)
    page_num = request.GET.get("page") or 1
    page_obj = paginator.get_page(page_num)

    qd = request.GET.copy()
    if "page" in qd:
        del qd["page"]
    querystring = qd.urlencode()

    ctx = {
        "items": page_obj.object_list,
        "page_obj": page_obj,
        "paginator": paginator,
        "querystring": querystring,
        "warehouses": warehouses,
        "default_dest_id": default_dest_id,
        "today": date.today(),
        "filter": {"q": q, "date_from": date_from, "date_to": date_to, "wh": wh_code},
    }
    return render(request, "purchase/injection/issues/list.html", ctx)

# ────────────────────────────────
# 출고(이동) 처리
# ────────────────────────────────
@require_POST
def issue_add(request, receipt_id: int):
    if not request.user.is_authenticated:
        return HttpResponseForbidden("로그인이 필요합니다.")

    payload = _parse_payload(request)
    if not payload:
        return HttpResponseBadRequest("잘못된 요청 바디(빈 요청)")

    dest_wh_id = payload.get("dest_wh_id")
    move_date  = _parse_move_date(payload.get("move_date"))
    remark     = (payload.get("remark") or "").strip()

    if not dest_wh_id:
        return HttpResponseBadRequest("이동할 창고를 선택하세요.")

    with transaction.atomic():
        receipt = (
            InjectionReceipt.objects
            .select_for_update()
            .select_related("warehouse", "order")
            .filter(id=receipt_id, is_active=True, is_deleted=False, is_used=False)
            .first()
        )
        if not receipt:
            return HttpResponseBadRequest("대상 입고 데이터를 찾을 수 없거나 이미 사용됨.")

        dest = Warehouse.objects.filter(id=dest_wh_id).first()
        if not dest:
            return HttpResponseBadRequest("이동할 창고가 존재하지 않습니다.")

        if receipt.warehouse_id == dest.id:
            return HttpResponseBadRequest("같은 창고로는 이동할 수 없습니다.")

        from_wh = receipt.warehouse

        issue = InjectionIssue.objects.create(
            receipt_lot=_make_issue_lot(receipt.id, move_date),
            date=move_date,
            qty=receipt.qty,   # 현재 UI는 전체 이동
            remark=remark,
            created_by=request.user,
            receipt=receipt,
            from_warehouse=from_wh,
            to_warehouse=dest,
            is_used_at_issue=False,
        )

        receipt.warehouse = dest
        receipt.save(update_fields=["warehouse"])

        logger.info(
            "[INJ-ISSUE] receipt_id=%s lot=%s from=%s to=%s qty=%s by=%s issue_id=%s",
            receipt.id, receipt.receipt_lot, getattr(from_wh, "warehouse_id", from_wh.id),
            getattr(dest, "warehouse_id", dest.id), receipt.qty, request.user.username, issue.id
        )

        return JsonResponse({
            "ok": True,
            "receipt_id": receipt.id,
            "from": getattr(from_wh, "warehouse_id", from_wh.id),
            "to": getattr(dest, "warehouse_id", dest.id),
            "issue_id": issue.id,
        })

@require_POST
def issue_add_bulk(request):
    if not request.user.is_authenticated:
        return HttpResponseForbidden("로그인이 필요합니다.")

    payload = _parse_payload(request)
    if not payload:
        return HttpResponseBadRequest("잘못된 요청 바디(빈 요청)")

    ids        = payload.get("ids") or []
    dest_wh_id = payload.get("dest_wh_id")
    move_date  = _parse_move_date(payload.get("move_date"))

    if not ids or not dest_wh_id:
        return HttpResponseBadRequest("이동 대상과 목적지 창고가 필요합니다.")

    dest = Warehouse.objects.filter(id=dest_wh_id).first()
    if not dest:
        return HttpResponseBadRequest("이동할 창고가 존재하지 않습니다.")

    results = {"moved": [], "skipped": []}
    with transaction.atomic():
        recs = (
            InjectionReceipt.objects
            .select_for_update()
            .select_related("warehouse", "order")
            .filter(id__in=ids, is_active=True, is_deleted=False, is_used=False)
        )
        for r in recs:
            if r.warehouse_id == dest.id:
                results["skipped"].append({"id": r.id, "reason": "same_warehouse"})
                continue

            issue = InjectionIssue.objects.create(
                receipt_lot=_make_issue_lot(r.id, move_date),
                date=move_date,
                qty=r.qty,
                remark="일괄이동",
                created_by=request.user,
                receipt=r,
                from_warehouse=r.warehouse,
                to_warehouse=dest,
                is_used_at_issue=False,
            )
            from_id = getattr(r.warehouse, "warehouse_id", r.warehouse_id)
            r.warehouse = dest
            r.save(update_fields=["warehouse"])

            logger.info(
                "[INJ-ISSUE-BULK] receipt_id=%s lot=%s from=%s to=%s qty=%s by=%s issue_id=%s",
                r.id, r.receipt_lot, from_id, getattr(dest, "warehouse_id", dest.id),
                r.qty, request.user.username, issue.id
            )
            results["moved"].append({"id": r.id, "issue_id": issue.id})

    return JsonResponse({"ok": True, **results})
