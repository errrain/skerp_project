from __future__ import annotations

# ── Standard Library ─────────────────────────────────────────────────────────
import csv
import json
import logging
from datetime import date, datetime, timedelta
from io import StringIO
from typing import Dict, Optional
from uuid import uuid4
from urllib.parse import urlencode

# ── Django Core ──────────────────────────────────────────────────────────────
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction, IntegrityError
from django.db.models import Sum, Max, OuterRef, Subquery, Case, When, Value, CharField, Exists, Q
from django.db.models.functions import TruncDate
from django.http import (
    HttpResponse, JsonResponse, HttpResponseBadRequest,
    HttpResponseForbidden, HttpResponseRedirect,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.timezone import now
from django.views.decorators.http import require_GET, require_http_methods, require_POST

# ── Domain Models (Apps) ─────────────────────────────────────────────────────
from master.models import Warehouse
from injectionorder.models import InjectionOrder, FlowStatus
from partnerorder.models import PartnerShipmentGroup, PartnerShipmentLine
from purchase.models import InjectionReceipt, InjectionIssue, InjectionReceiptLine
from quality.inspections.models import (
    IncomingInspection, IncomingInspectionDetail, QCStatus,
)

logger = logging.getLogger(__name__)

PAGE_SIZE = 20  # 리스트 페이징 크기

# ─────────────────────────────────────────────────────────────────────────────
# 상수/유틸
# ─────────────────────────────────────────────────────────────────────────────

# 기본 입고창고 코드(사출품 전용)
DEFAULT_WH_CODE = "sk_wh_5"


def _new_issue_batch_id() -> str:
    """이슈 묶음(batch) 식별용 짧은 유니크 문자열"""
    return uuid4().hex


def _today_local() -> date:
    try:
        if getattr(settings, "USE_TZ", False):
            return timezone.localdate()
        return date.today()
    except Exception:
        return date.today()


def _date_7days_window() -> tuple[date, date]:
    """(from, to) = (오늘-7일, 오늘)"""
    to_d = _today_local()
    from_d = to_d - timedelta(days=7)
    return from_d, to_d


def _parse_move_date(s: Optional[str]) -> date:
    if not s:
        return _today_local()
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return _today_local()


def _parse_payload(request) -> Dict:
    from urllib.parse import parse_qs
    ctype = request.META.get("CONTENT_TYPE", "")
    raw = request.body or b""
    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception:
        text = str(raw)

    logger.debug("[REQ] ctype=%s len=%s body[:200]=%r", ctype, len(raw), text[:200])

    if "application/json" in ctype:
        try:
            return json.loads(text)
        except Exception as e:
            logger.warning("JSON parse error: %s; body[:120]=%r", e, text[:120])

    if request.POST:
        return request.POST.dict()

    if text:
        try:
            qd = {k: (v[0] if isinstance(v, list) else v) for k, v in parse_qs(text).items()}
            return qd
        except Exception as e:
            logger.warning("parse_qs error: %s", e)

    return {}


def _next_receipt_lot(d: date) -> str:
    """헤더 LOT: IN + YYYYMMDD + 3자리"""
    prefix = d.strftime("IN%Y%m%d")
    last = (
        InjectionReceipt.objects
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


def _get_default_wh() -> Optional[Warehouse]:
    return (
        Warehouse.objects
        .filter(is_deleted="N", warehouse_id=DEFAULT_WH_CODE)
        .first()
        or Warehouse.objects.filter(is_deleted="N").order_by("id").first()
    )


def _resolve_receipt_warehouse(request) -> Optional[Warehouse]:
    qs = Warehouse.objects.filter(is_deleted="N")
    code = (request.POST.get("warehouse_code") or "").strip()
    if code:
        wh = qs.filter(warehouse_id=code).first()
        if wh:
            return wh
    wh = qs.filter(warehouse_id=DEFAULT_WH_CODE).first()
    if wh:
        return wh
    return qs.order_by("id").first()


def _create_issue_and_number(
    *, user, move_date, qty, from_wh, to_wh,
    receipt, remark="", receipt_line=None, batch_id=None
):
    """
    1) 임시번호로 INSERT (UNIQUE 회피)
    2) 최종번호로 UPDATE (중복 시 -01, -02 ... 접미사 부여)
    """
    if not from_wh or not to_wh:
        raise ValueError("from_warehouse, to_warehouse는 필수입니다.")
    if getattr(from_wh, "id", None) == getattr(to_wh, "id", None):
        raise ValueError("같은 창고로는 이동할 수 없습니다.")

    # 1) INSERT with TMP번호 (정확히 20자)
    tmp_no = "TMP" + uuid4().hex[:17]  # 3 + 17 = 20
    issue = InjectionIssue.objects.create(
        receipt_lot=tmp_no,
        date=move_date,
        qty=qty,
        remark=remark,
        created_by=user,
        receipt=receipt,
        from_warehouse=from_wh,
        to_warehouse=to_wh,
        receipt_line=receipt_line,
        batch_id=batch_id,
        is_used_at_issue=False,
    )

    # 2) 최종번호 산출: ISYYYYMMDD + 6자리 receipt.id
    base_no = f"IS{move_date.strftime('%Y%m%d')}{receipt.id:06d}"  # 16자
    final_no = base_no

    # 이미 같은 번호가 있으면 -01, -02 ...로 붙여서 20자 내 보장
    if InjectionIssue.objects.filter(receipt_lot=final_no).exclude(id=issue.id).exists():
        # 기존 suffix 확인
        siblings = (
            InjectionIssue.objects
            .filter(receipt_lot__startswith=base_no)
            .exclude(id=issue.id)
            .values_list("receipt_lot", flat=True)
        )
        # 존재하는 suffix 수집
        used = set()
        for s in siblings:
            if len(s) > len(base_no) and s.startswith(base_no + "-"):
                suf = s[len(base_no) + 1:]  # '-' 뒤
                if suf.isdigit():
                    used.add(int(suf))
        # 다음 번호 찾기 (01부터)
        n = 1
        while True:
            cand = f"{base_no}-{n:02d}"  # 18~19자
            if len(cand) > 20:
                # 100 이상이면 3자리 시도(최대 20자까지 허용)
                cand = f"{base_no}-{n}"
                if len(cand) > 20:
                    raise ValueError("이슈 번호가 20자를 초과합니다.")
            if n not in used and not InjectionIssue.objects.filter(receipt_lot=cand).exclude(id=issue.id).exists():
                final_no = cand
                break
            n += 1

    # UPDATE 최종번호
    issue.receipt_lot = final_no
    issue.save(update_fields=["receipt_lot"])
    return issue

def _next_issue_lot(move_date):
    """
    (예비) ISYYYYMMDD + 6자리 시퀀스.
    같은 날짜 prefix의 최댓값을 잡고 +1. (트랜잭션 내 select_for_update로 충돌 완화)
    """
    prefix = f"IS{move_date.strftime('%Y%m%d')}"
    with transaction.atomic():
        last = (
            InjectionIssue.objects
            .select_for_update()
            .filter(receipt_lot__startswith=prefix)
            .order_by('-receipt_lot')
            .values_list('receipt_lot', flat=True)
            .first()
        )
        seq = int(last[-6:]) + 1 if last else 1
    return f"{prefix}{seq:06d}"


def _sync_receipt_header_warehouse(receipt: InjectionReceipt):
    """
    모든 라인의 창고가 동일하면 헤더 창고를 그 값으로 동기화.
    혼재되어 있으면 헤더는 그대로 둔다(표시/레거시 호환).
    """
    qs = InjectionReceiptLine.objects.filter(receipt=receipt).values_list('warehouse_id', flat=True)
    wh_ids = list(qs)
    if not wh_ids:
        return
    uniq = set(wh_ids)
    if len(uniq) == 1:
        only_id = next(iter(uniq))
        if receipt.warehouse_id != only_id:
            receipt.warehouse_id = only_id
            receipt.save(update_fields=['warehouse'])


def _bad(msg: str, *, reason: str = None, status: int = 400, extra: dict | None = None):
    # 공통 에러 응답(JSON)
    payload = {"ok": False, "msg": msg}
    if reason:
        payload["reason"] = reason
    if extra:
        payload["extra"] = extra
    return JsonResponse(payload, status=status)

@login_required
def issue_group_fragment(request, receipt_id: int):
    """
    부분/전체 이동 성공 후, 해당 receipt 그룹만 다시 렌더링해서 돌려준다.
    쿼리파라미터:
      - current_wh: 현재 리스트 필터(예: 'sk_wh_5')
    응답(JSON):
      - {ok: true, remove: true}  -> 현재 위치에 남은 서브라인이 없으므로, 프론트에서 tbody 제거
      - {ok: true, html: "<tr>...</tr>..."} -> tbody.innerHTML로 교체
    """
    current_wh = (request.GET.get("current_wh") or "").strip()

    # 헤더 조회
    r = (
        InjectionReceipt.objects
        .select_related("warehouse", "order")
        .filter(id=receipt_id, is_active=True, is_deleted=False)
        .first()
    )
    if not r:
        return JsonResponse({"ok": False, "msg": "헤더 LOT을 찾을 수 없습니다."}, status=404)

    # 제품명 계산(원래 리스트와 동일한 안전 로직)
    name = "-"
    try:
        first_item_mgr = getattr(r.order, "items", None)
        first_item = first_item_mgr.all().first() if first_item_mgr is not None else None
        if first_item:
            name = (
                getattr(getattr(first_item, "product", None), "name", None)
                or getattr(getattr(first_item, "injection", None), "name", None)
                or getattr(first_item, "name", "")
            ) or "-"
        if name == "-":
            name = (
                getattr(getattr(r.order, "product", None), "name", None)
                or getattr(r.order, "product_name", None)
                or getattr(r.order, "item_name", None)
                or "-"
            )
    except Exception:
        pass
    r.product_display = name or "-"

    # 서브라인 재조회: 현재 위치(current_wh)에 남아있는 라인만
    lines_qs = InjectionReceiptLine.objects.filter(receipt_id=r.id).select_related("warehouse").order_by("sub_seq")
    if current_wh:
        # 기본: 라인.warehouse의 code가 current_wh 인 것
        # 레거시 데이터 대비: 라인.warehouse가 NULL이면 헤더 창고 코드로 간주
        lines_qs = lines_qs.filter(
            Q(warehouse__warehouse_id=current_wh) |
            Q(warehouse__isnull=True, receipt__warehouse__warehouse_id=current_wh)
        )
    sl = list(lines_qs)

    # 창고 목록 + 기본 목적지
    warehouses = list(Warehouse.objects.filter(is_deleted="N").order_by("warehouse_id"))
    default_dest_id = next(
        (w.id for w in warehouses if getattr(w, "warehouse_id", None) == "sk_wh_9"),
        (warehouses[0].id if warehouses else None),
    )

    if not sl:
        return JsonResponse({"ok": True, "remove": True})

    html = render(
        request,
        "purchase/injection/issues/_group_rows.html",
        {"r": r, "sl": sl, "warehouses": warehouses, "default_dest_id": default_dest_id},
    ).content.decode("utf-8")

    return JsonResponse({"ok": True, "html": html})
# ─────────────────────────────────────────────────────────────────────────────
# Subquery: 최신 검사 상태/일시, 최신 입고 LOT
# ─────────────────────────────────────────────────────────────────────────────

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

# ─────────────────────────────────────────────────────────────────────────────
# 공통: 주문 리스트 쿼리 + 필터 + 기본 날짜(오늘-7 ~ 오늘)
# ─────────────────────────────────────────────────────────────────────────────

def _build_receipt_order_queryset(request, for_export: bool = False):
    """
    리스트/엑셀 공통 쿼리 구성.
    - 기본 필터: 진행상태 PRT/RCV & dlt_yn='N'
    - 검색 파라미터 적용
    - 날짜 필터 기본값: 제공 안 되었을 때 '오늘-7일 ~ 오늘'
    """
    has_receipt = Exists(
        InjectionReceipt.objects.filter(order=OuterRef("pk"), is_deleted=False)
    )

    qs = (
        InjectionOrder.objects
        .filter(flow_status__in=[FlowStatus.PRT, FlowStatus.RCV], dlt_yn="N")
        .select_related("vendor")
        .prefetch_related("items")
        .annotate(
            qty_sum=Sum("items__quantity"),
            latest_insp_status=Subquery(_latest_insp_status),
            latest_insp_date=Subquery(_latest_insp_date),
            latest_receipt_lot=Subquery(_latest_receipt_lot),
            shipping_date=TruncDate("shipping_registered_at"),
            insp_status_display=Case(
                When(latest_insp_status__in=[QCStatus.PASS, "PASS", "합격"], then=Value("합격")),
                When(latest_insp_status__in=[QCStatus.FAIL, "FAIL", "불합격"], then=Value("불합격")),
                When(latest_insp_status__in=[QCStatus.HOLD, "HOLD", "보류"], then=Value("보류")),
                When(latest_insp_status__in=[QCStatus.DRAFT, "DRAFT", "대기"], then=Value("대기")),
                default=Value("-"),
                output_field=CharField(),
            ),
            status_display=Case(
                When(has_receipt, then=Value("입고완료")),
                default=Value("입고대기"),
                output_field=CharField(),
            ),
        )
        .order_by("-latest_insp_date", "-id")
    )

    # 파라미터
    vendor          = (request.GET.get("vendor") or "").strip()
    product         = (request.GET.get("product") or "").strip()
    order_date_from = (request.GET.get("order_date_from") or "").strip()
    order_date_to   = (request.GET.get("order_date_to") or "").strip()
    insp_date_from  = (request.GET.get("insp_date_from") or "").strip()
    insp_date_to    = (request.GET.get("insp_date_to") or "").strip()
    status          = (request.GET.get("status") or "").strip()

    # 기본 날짜(오늘-7 ~ 오늘) 적용: 사용자가 아무것도 안 준 경우만
    odf_default, odt_default = _date_7days_window()
    idf_default, idt_default = odf_default, odt_default  # 검사도 동일 기준

    use_order_default = not order_date_from and not order_date_to
    use_insp_default  = not insp_date_from and not insp_date_to

    if vendor:
        qs = qs.filter(vendor__name__icontains=vendor)
    if product:
        qs = qs.filter(items__injection__name__icontains=product)

    if use_order_default:
        qs = qs.filter(order_date__range=[odf_default, odt_default])
    else:
        if order_date_from:
            qs = qs.filter(order_date__gte=order_date_from)
        if order_date_to:
            qs = qs.filter(order_date__lte=order_date_to)

    if use_insp_default:
        qs = qs.filter(latest_insp_date__range=[idf_default, idt_default])
    else:
        if insp_date_from:
            qs = qs.filter(latest_insp_date__gte=insp_date_from)
        if insp_date_to:
            qs = qs.filter(latest_insp_date__lte=insp_date_to)

    if status in ("입고대기", "입고완료"):
        qs = qs.filter(status_display=status)

    # 템플릿/엑셀에서 현재 필터 값을 알 수 있도록 반환용 dict 구성
    filter_ctx = {
        "vendor": vendor,
        "product": product,
        "order_date_from": order_date_from or odf_default.strftime("%Y-%m-%d"),
        "order_date_to":   order_date_to   or odt_default.strftime("%Y-%m-%d"),
        "insp_date_from":  insp_date_from  or idf_default.strftime("%Y-%m-%d"),
        "insp_date_to":    insp_date_to    or idt_default.strftime("%Y-%m-%d"),
        "status": status,
    }
    return qs.distinct(), filter_ctx

# ─────────────────────────────────────────────────────────────────────────────
# 입고 목록 (주문 단위)
# ─────────────────────────────────────────────────────────────────────────────

@require_http_methods(["GET"])
def receipt_list(request):
    """
    사출 입고 목록(주문단위)
    - 기존 로직 유지 + 페이징 + 기본 날짜 필터(오늘-7 ~ 오늘)
    """
    qs, filter_ctx = _build_receipt_order_queryset(request)

    paginator = Paginator(qs, PAGE_SIZE)
    page_number = request.GET.get("page") or 1
    page_obj = paginator.get_page(page_number)

    # 페이징 번호(±2) + querystring(엑셀/페이징 유지)
    num = page_obj.number
    start = max(1, num - 2)
    end = min(paginator.num_pages, num + 2)
    page_range = range(start, end + 1)

    qd = request.GET.copy()
    querystring = qd.urlencode()  # 엑셀 버튼에서 그대로 사용
    qd.pop("page", None)
    querystring_wo_page = qd.urlencode()

    return render(request, "purchase/injection/receipts/list.html", {
        "page_obj": page_obj,
        "page_range": page_range,
        "today": _today_local(),
        "filter": filter_ctx,
        "querystring": querystring,
        "querystring_wo_page": querystring_wo_page,
    })

# 기존 템플릿/URL에서 사용 중인 이름이 'inj_receipt_list' 이면 아래 alias 로 호환
inj_receipt_list = receipt_list

# ─────────────────────────────────────────────────────────────────────────────
# 엑셀(CSV) 다운로드 – 현재 검색조건 유지
# ─────────────────────────────────────────────────────────────────────────────

@require_GET
def inj_receipt_export(request):
    """
    사출 입고 목록 CSV 내보내기
    - 인코딩: UTF-8 with BOM (Excel 한글 깨짐 방지)
    - prefetch_related() 이후 iterator() 사용 시 chunk_size 필수
    """
    has_receipt = Exists(
        InjectionReceipt.objects.filter(order=OuterRef("pk"), is_deleted=False)
    )

    qs = (
        InjectionOrder.objects
        .filter(flow_status__in=[FlowStatus.PRT, FlowStatus.RCV], dlt_yn="N")
        .select_related("vendor")
        .prefetch_related("items")
        .annotate(
            qty_sum=Sum("items__quantity"),
            latest_insp_status=Subquery(_latest_insp_status),
            latest_insp_date=Subquery(_latest_insp_date),
            latest_receipt_lot=Subquery(_latest_receipt_lot),
            shipping_date=TruncDate("shipping_registered_at"),
            insp_status_display=Case(
                When(latest_insp_status__in=[QCStatus.PASS, "PASS", "합격"], then=Value("합격")),
                When(latest_insp_status__in=[QCStatus.FAIL, "FAIL", "불합격"], then=Value("불합격")),
                When(latest_insp_status__in=[QCStatus.HOLD, "HOLD", "보류"], then=Value("보류")),
                When(latest_insp_status__in=[QCStatus.DRAFT, "DRAFT", "대기"], then=Value("대기")),
                default=Value("-"),
                output_field=CharField(),
            ),
            status_display=Case(
                When(has_receipt, then=Value("입고완료")),
                default=Value("입고대기"),
                output_field=CharField(),
            ),
        )
        .order_by("-latest_insp_date", "-id")
    )

    # 동일한 필터 적용
    vendor          = (request.GET.get("vendor") or "").strip()
    product         = (request.GET.get("product") or "").strip()
    order_date_from = (request.GET.get("order_date_from") or "").strip()
    order_date_to   = (request.GET.get("order_date_to") or "").strip()
    insp_date_from  = (request.GET.get("insp_date_from") or "").strip()
    insp_date_to    = (request.GET.get("insp_date_to") or "").strip()
    status          = (request.GET.get("status") or "").strip()

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
    if status in ("입고대기", "입고완료"):
        qs = qs.filter(status_display=status)

    # CSV 작성 (UTF-8 with BOM)
    buffer = StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(["발주LOT", "발주처", "품명", "수량", "발주일", "배송일", "검사일", "검사결과", "상태", "입고헤더LOT"])

    for o in qs.iterator(chunk_size=1000):
        first = getattr(o, "items", None)
        first = first.first() if first is not None else None
        item_name = (
            (getattr(getattr(first, "injection", None), "name", None) if first else None)
            or getattr(getattr(o, "product", None), "name", None)
            or getattr(o, "product_name", None)
            or getattr(o, "item_name", None)
            or "-"
        )

        writer.writerow([
            o.order_lot or "",
            getattr(o.vendor, "name", "") or "",
            item_name,
            (o.qty_sum or 0),
            o.order_date.strftime("%Y-%m-%d") if o.order_date else "",
            o.shipping_date.strftime("%Y-%m-%d") if o.shipping_date else "",
            o.latest_insp_date.strftime("%Y-%m-%d") if o.latest_insp_date else "",
            o.insp_status_display or "-",
            o.status_display or "-",
            o.latest_receipt_lot or "",
        ])

    csv_data = buffer.getvalue()
    buffer.close()

    bom = "\ufeff"  # BOM
    filename = f"injection_receipts_{_today_local().strftime('%Y%m%d')}.csv"
    resp = HttpResponse(
        (bom + csv_data),
        content_type="text/csv; charset=utf-8",
    )
    resp["Content-Disposition"] = f'attachment; filename="{filename}"; filename*=UTF-8\'\'{filename}'
    return resp

# ─────────────────────────────────────────────────────────────────────────────
# 입고 저장 (주문 단위 일괄)
# ─────────────────────────────────────────────────────────────────────────────

@require_http_methods(["POST"])
@transaction.atomic
def receipt_add(request, order_id: int | None = None):
    selected_ids = request.POST.getlist("selected_ids")
    if order_id and str(order_id) not in selected_ids:
        selected_ids.append(str(order_id))
    if not selected_ids:
        messages.warning(request, "선택된 행이 없습니다.")
        return redirect("purchase:inj_receipt_list")

    rec_date_str = request.POST.get("receipt_date") or _today_local().strftime("%Y-%m-%d")
    try:
        rec_date = datetime.strptime(rec_date_str, "%Y-%m-%d").date()
    except ValueError:
        rec_date = _today_local()

    wh = _get_default_wh()
    if not wh:
        messages.error(request, "기본 창고(wh5)를 찾을 수 없습니다.")
        return redirect("purchase:inj_receipt_list")

    orders = (
        InjectionOrder.objects
        .select_for_update()
        .select_related("vendor")
        .prefetch_related("items")
        .filter(pk__in=selected_ids, dlt_yn="N")
    )

    success = skipped = 0
    PASS_VALUES = {QCStatus.PASS, "PASS", "합격"}

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
        lot = _next_receipt_lot(rec_date)

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
            success += 1
        except Exception as e:
            logger.exception("입고 저장 실패 (order_id=%s, lot=%s) : %s", order.pk, lot, e)
            skipped += 1

    if success:
        messages.success(request, f"입고 완료 {success}건 (스킵 {skipped}건)")
    else:
        messages.warning(request, f"처리된 입고 건이 없습니다. (스킵 {skipped}건)")
    return redirect("purchase:inj_receipt_list")

# ─────────────────────────────────────────────────────────────────────────────
# 출고(이동) 목록/저장
# ─────────────────────────────────────────────────────────────────────────────

@require_GET
def issue_list(request):
    # 기본 기간: 오늘-7 ~ 오늘
    today = _today_local()
    default_from = today - timedelta(days=7)

    q          = (request.GET.get("q") or "").strip()
    date_from  = (request.GET.get("date_from") or default_from.strftime("%Y-%m-%d")).strip()
    date_to    = (request.GET.get("date_to") or today.strftime("%Y-%m-%d")).strip()
    wh_code_in = (request.GET.get("wh") or "").strip()
    use_status = (request.GET.get("use_status") or "").strip()

    # 요청이 없으면 기본 창고 고정(wh5)
    effective_wh = wh_code_in or DEFAULT_WH_CODE

    # 1) 기간/사용가능 헤더 먼저
    header_qs = (
        InjectionReceipt.objects
        .filter(is_active=True, is_deleted=False, is_used=False)
        .select_related("order", "warehouse")
        .order_by("-date", "-id")
    )
    if date_from:
        header_qs = header_qs.filter(date__gte=date_from)
    if date_to:
        header_qs = header_qs.filter(date__lte=date_to)

    receipts = list(header_qs)
    rec_ids  = [r.id for r in receipts] or [0]

    # 2) 라인(서브 LOT) 실위치 기준 필터
    #    - 라인.warehouse 코드가 선택값
    #    - 라인.warehouse가 NULL이면 헤더.warehouse 코드로 간주
    lines_qs = (
        InjectionReceiptLine.objects
        .filter(receipt_id__in=rec_ids)
        .select_related("warehouse", "receipt", "receipt__warehouse")
        .order_by("sub_seq")
        .filter(
            Q(warehouse__warehouse_id=effective_wh) |
            Q(warehouse__isnull=True, receipt__warehouse__warehouse_id=effective_wh)
        )
    )

    allowed_status = {"미사용", "부분사용", "사용완료"}
    if use_status in allowed_status:
        lines_qs = lines_qs.filter(use_status=use_status)

    # 3) receipt별 라인 묶기(라인이 한 개도 없으면 해당 헤더 제외)
    lines_by_receipt: dict[int, list] = {}
    for ln in lines_qs:
        lines_by_receipt.setdefault(ln.receipt_id, []).append(ln)

    filtered_receipts = [r for r in receipts if r.id in lines_by_receipt]

    # 4) 품명 표시 + 라인 부착
    q_lower = q.lower()
    items = []
    for r in filtered_receipts:
        # 품명 표시(폴백 안전)
        name = "-"
        try:
            first_item_qs = getattr(r.order, "items", None)
            first_item = first_item_qs.all().first() if first_item_qs is not None else None
            if first_item:
                name = (
                    getattr(getattr(first_item, "product", None), "name", None)
                    or getattr(getattr(first_item, "injection", None), "name", None)
                    or getattr(first_item, "name", "")
                    or "-"
                )
            if name == "-":
                name = (
                    getattr(getattr(r.order, "product", None), "name", None)
                    or getattr(r.order, "product_name", None)
                    or getattr(r.order, "item_name", None)
                    or "-"
                )
        except Exception:
            pass
        r.product_display = name or "-"
        r.sub_lines = lines_by_receipt.get(r.id, [])

        if q:
            if (r.product_display or "").lower().find(q_lower) != -1:
                items.append(r)
        else:
            items.append(r)

    # 5) 페이징
    paginator = Paginator(items, 20)
    page_num = request.GET.get("page") or 1
    page_obj = paginator.get_page(page_num)

    qd = request.GET.copy()
    qd.pop("page", None)
    querystring = qd.urlencode()

    warehouses = list(Warehouse.objects.filter(is_deleted="N").order_by("warehouse_id"))

    default_dest_id = next(
        (w.id for w in warehouses if getattr(w, "warehouse_id", None) == "sk_wh_9"),
        (warehouses[0].id if warehouses else None),
    )

    ctx = {
        "items": page_obj.object_list,
        "page_obj": page_obj,
        "paginator": paginator,
        "querystring": querystring,
        "warehouses": warehouses,
        "default_dest_id": default_dest_id,
        "today": today,
        "filter": {
            "q": q,
            "date_from": date_from,
            "date_to": date_to,
            "wh": effective_wh,  # 선택값 유지
            "use_status": use_status,
        },
        "selected_wh": effective_wh,
        "DEFAULT_WH_CODE": DEFAULT_WH_CODE,
    }
    return render(request, "purchase/injection/issues/list.html", ctx)


@require_POST
def issue_add(request, receipt_id: int):
    if not request.user.is_authenticated:
        return _bad("로그인이 필요합니다.", reason="auth", status=403)

    payload = _parse_payload(request)
    if not payload:
        return _bad("잘못된 요청 바디(빈 요청)", reason="empty_body")

    try:
        dest_wh_id = int(payload.get("dest_wh_id"))
    except (TypeError, ValueError):
        dest_wh_id = None
    move_date  = _parse_move_date(payload.get("move_date"))
    remark     = (payload.get("remark") or "").strip()

    raw_sub_ids = payload.get("sub_line_ids") or []
    if isinstance(raw_sub_ids, (list, tuple)):
        try:
            sub_ids = sorted({int(x) for x in raw_sub_ids})
        except (TypeError, ValueError):
            sub_ids = []
    else:
        sub_ids = []

    if not dest_wh_id:
        return _bad("이동할 창고를 선택하세요.", reason="no_dest")

    with transaction.atomic():
        receipt = (
            InjectionReceipt.objects
            .select_for_update()
            .select_related("warehouse", "order")
            .filter(id=receipt_id, is_active=True, is_deleted=False, is_used=False)
            .first()
        )
        if not receipt:
            return _bad("대상 입고 데이터를 찾을 수 없거나 이미 사용됨.",
                        reason="no_receipt", extra={"receipt_id": receipt_id})

        dest = Warehouse.objects.filter(id=dest_wh_id, is_deleted="N").first()
        if not dest:
            return _bad("이동할 창고가 존재하지 않습니다.",
                        reason="no_dest_wh", extra={"dest_wh_id": dest_wh_id})

        # ----- 부분 이동(서브 LOT 지정) -----
        if sub_ids:
            line_qs = (
                InjectionReceiptLine.objects
                .filter(receipt_id=receipt.id, id__in=sub_ids)
                .select_for_update()
            )
            lines = list(line_qs)
            if not lines:
                return _bad("선택된 서브 LOT이 없습니다.",
                            reason="no_lines", extra={"receipt_id": receipt.id, "sub_ids": sub_ids})

            movable, skipped = [], []
            for ln in lines:
                if ln.warehouse_id == dest.id:
                    skipped.append(ln)
                else:
                    movable.append(ln)

            if not movable:
                return _bad("이미 해당 창고에 있는 서브 LOT 입니다.",
                            reason="already_there",
                            extra={"dest_id": dest.id,
                                   "line_ids": [ln.id for ln in lines],
                                   "skipped_ids": [ln.id for ln in skipped]})

            batch_id = _new_issue_batch_id()
            moved_ids = []

            for ln in movable:
                from_wh = ln.warehouse or receipt.warehouse
                ln.warehouse = dest
                ln.save(update_fields=["warehouse"])
                moved_ids.append(ln.id)

                _create_issue_and_number(
                    receipt=receipt,
                    move_date=move_date,
                    qty=ln.qty,
                    remark=remark,
                    from_wh=from_wh,
                    to_wh=dest,
                    user=request.user,
                    receipt_line=ln,
                    batch_id=batch_id,
                )

            all_to_dest = not InjectionReceiptLine.objects.filter(
                receipt_id=receipt.id
            ).exclude(warehouse_id=dest.id).exists()
            if all_to_dest and receipt.warehouse_id != dest.id:
                receipt.warehouse = dest
                receipt.save(update_fields=["warehouse"])

            return JsonResponse({
                "ok": True,
                "moved": len(movable),
                "moved_ids": moved_ids,
                "skipped_ids": [ln.id for ln in skipped],
                "batch_id": batch_id,
            })

        # ----- 전체 이동(헤더 단위) -----
        lines_qs = (
            InjectionReceiptLine.objects
            .filter(receipt_id=receipt.id)
            .select_for_update()
        )

        src_ids = set(lines_qs.values_list("warehouse_id", flat=True))
        if len(src_ids) == 1:
            only_src_id = next(iter(src_ids))
            from_wh_for_issue = Warehouse.objects.filter(id=only_src_id).first() or receipt.warehouse
        else:
            from_wh_for_issue = receipt.warehouse

        movable_qs = lines_qs.exclude(warehouse_id=dest.id)
        movable_cnt = movable_qs.count()
        if movable_cnt == 0:
            return _bad("이미 모든 서브 LOT이 해당 창고에 있습니다.",
                        reason="all_there",
                        extra={"dest_id": dest.id, "receipt_id": receipt.id})

        movable_qs.update(warehouse=dest)

        if receipt.warehouse_id != dest.id:
            receipt.warehouse = dest
            receipt.save(update_fields=["warehouse"])

        total_qty = lines_qs.aggregate(total=Sum("qty"))["total"] or 0

        _create_issue_and_number(
            receipt=receipt,
            move_date=move_date,
            qty=total_qty,
            remark=remark,
            from_wh=from_wh_for_issue,
            to_wh=dest,
            user=request.user,
            receipt_line=None,
            batch_id=_new_issue_batch_id(),
        )

        return JsonResponse({"ok": True, "moved": movable_cnt})

@require_POST
def issue_add_bulk(request):
    if not request.user.is_authenticated:
        return HttpResponseForbidden("로그인이 필요합니다.")

    payload = _parse_payload(request)
    ids       = payload.get("ids") or []
    dest_wh_id= payload.get("dest_wh_id")
    move_date = _parse_move_date(payload.get("move_date"))
    remark    = (payload.get("remark") or "").strip()

    if not ids:
        return HttpResponseBadRequest("이동 대상이 없습니다.")
    if not dest_wh_id:
        return HttpResponseBadRequest("이동할 창고를 선택하세요.")

    dest = Warehouse.objects.filter(id=dest_wh_id, is_deleted="N").first()
    if not dest:
        return HttpResponseBadRequest("이동할 창고가 존재하지 않습니다.")

    results = []
    batch_id = _new_issue_batch_id()

    for rid in ids:
        with transaction.atomic():
            receipt = (
                InjectionReceipt.objects
                .select_for_update()
                .select_related("warehouse")
                .filter(id=rid, is_active=True, is_deleted=False, is_used=False)
                .first()
            )
            if not receipt:
                results.append({"id": rid, "ok": False, "msg": "입고 데이터 없음/사용불가"})
                continue

            lines_qs = InjectionReceiptLine.objects.select_for_update().filter(receipt_id=receipt.id)
            movable_qs = lines_qs.exclude(warehouse_id=dest.id)
            movable_cnt = movable_qs.count()
            if movable_cnt == 0:
                results.append({"id": rid, "ok": False, "msg": "이미 목적지"})
                continue

            # 출발 창고(from_wh) 결정
            src_ids = set(lines_qs.values_list("warehouse_id", flat=True))
            if len(src_ids) == 1:
                only_src_id = next(iter(src_ids))
                from_wh_for_issue = Warehouse.objects.filter(id=only_src_id).first() or receipt.warehouse
            else:
                from_wh_for_issue = receipt.warehouse

            # 라인 이동
            movable_qs.update(warehouse=dest)

            # 헤더 동기화
            if receipt.warehouse_id != dest.id:
                receipt.warehouse = dest
                receipt.save(update_fields=["warehouse"])

            total_qty = lines_qs.aggregate(total=Sum("qty"))["total"] or 0
            _create_issue_and_number(
                receipt=receipt,
                move_date=move_date,
                qty=total_qty,
                remark=remark,
                from_wh=from_wh_for_issue,   # ✅ 보장
                to_wh=dest,
                user=request.user,
                receipt_line=None,
                batch_id=batch_id,
            )
            results.append({"id": rid, "ok": True, "moved": movable_cnt})

    moved_total = sum(r.get("moved", 0) for r in results if r.get("ok"))
    return JsonResponse({"ok": True, "batch_id": batch_id, "moved_total": moved_total, "results": results})

# ─────────────────────────────────────────────────────────────────────────────
# PASS 라인 후보(발주 LOT) – 입고상태/LOT 주석 포함
# ─────────────────────────────────────────────────────────────────────────────

@require_http_methods(["GET"])
def receipt_candidates(request, order_id):
    """
    발주(order_id)의 '최신 검사 기준 PASS' 배송 하위라인 후보 표시
    - 입고 여부/최근 LOT은 IncomingInspectionDetail → ReceiptLine → Receipt를 통해 계산
    - 헤더 LOT은 receipt__receipt_lot로 직접 서브쿼리
    """
    order = get_object_or_404(InjectionOrder, pk=order_id)

    # 1) 라인별 최신 검사(detail)
    latest_detail_qs = (
        IncomingInspectionDetail.objects
        .filter(shipment_line=OuterRef("pk"))
        .order_by("-created_at", "-id")
    )

    # 2) 라인 전체 기준으로 ReceiptLine/LOT 서브쿼리
    rl_for_line = InjectionReceiptLine.objects.filter(
        detail__shipment_line=OuterRef("pk")
    )
    last_rl_id_sq = Subquery(rl_for_line.order_by("-id").values("id")[:1])
    last_rcpt_lot_sq = Subquery(
        rl_for_line.order_by("-id").values("receipt__receipt_lot")[:1]
    )
    last_sub_lot_sq = Subquery(
        rl_for_line.order_by("-id").values("sub_lot")[:1]
    )

    # 3) 기본 라인 쿼리 + 주석치기
    base_lines = (
        PartnerShipmentLine.objects
        .select_related("shipment", "shipment__order")
        .filter(
            shipment__order=order,
            shipment__dlt_yn="N",
            dlt_yn="N",
        )
        .annotate(
            latest_status=Subquery(latest_detail_qs.values("status")[:1]),
            latest_detail_id=Subquery(latest_detail_qs.values("id")[:1]),
            latest_detail_qty=Subquery(latest_detail_qs.values("qty")[:1]),
            latest_insp_date=Subquery(
                latest_detail_qs.values("inspection__inspection_date")[:1]
            ),
            ship_date=Subquery(
                PartnerShipmentGroup.objects
                .filter(pk=OuterRef("shipment_id"))
                .values("ship_date")[:1]
            ),
            already_received=Exists(rl_for_line),
            rl_id=last_rl_id_sq,
            receipt_lot=last_rcpt_lot_sq,  # 헤더 LOT
            sub_lot=last_sub_lot_sq,        # 서브 LOT
        )
        .filter(latest_status__in=[QCStatus.PASS, "PASS", "합격"])
        .order_by("shipment__group_no", "sub_seq", "id")
    )

    # 4) 템플릿용 dict
    candidates = []
    for ln in base_lines:
        qty = int(ln.latest_detail_qty or getattr(ln, "qty", 0) or 0)
        label = f"{getattr(ln.shipment, 'group_no', '')}-{ln.sub_seq} : {qty}"
        candidates.append({
            "label": label,
            "detail_id": ln.latest_detail_id,     # 커밋 시 사용
            "qty": qty,
            "production_date": getattr(ln, "production_date", None),
            "ship_date": ln.ship_date,
            "insp_date": ln.latest_insp_date,
            "already_received": bool(ln.already_received),
            "rl_id": ln.rl_id,                    # 취소 시 사용
            "receipt_lot": ln.receipt_lot,        # 헤더 LOT
            "sub_lot": ln.sub_lot,                # 서브 LOT
        })

    # 5) 상단 발주 요약(발주처/품명/수량/발주일)
    try:
        partner_name = (
            getattr(getattr(order, "vendor", None), "name", None)
            or getattr(getattr(order, "partner", None), "name", None)
            or getattr(order, "partner_name", "")
            or getattr(order, "vendor_name", "")
        )
    except Exception:
        partner_name = ""

    item_name = ""
    try:
        first_item = getattr(order, "items", None)
        first_item = first_item.all().first() if first_item is not None else None
        if first_item:
            item_name = (
                getattr(getattr(first_item, "injection", None), "name", None)
                or getattr(getattr(first_item, "product", None), "name", None)
                or getattr(first_item, "name", "")
            ) or ""
        if not item_name:
            item_name = getattr(order, "item_name", "") or getattr(order, "product_name", "")
    except Exception:
        pass

    try:
        ordered_qty = order.items.aggregate(s=Sum("quantity"))["s"]
    except Exception:
        ordered_qty = getattr(order, "order_qty", None) or getattr(order, "ordered_qty", None)

    order_info = {
        "lot": getattr(order, "order_lot", ""),
        "partner": partner_name,
        "item": item_name,
        "ordered_qty": ordered_qty or 0,
        "order_date": getattr(order, "order_date", None),
    }

    # 커밋 직후 전달된 헤더 LOT(상단 알림용)
    rcpt_lot = (request.GET.get("rcpt") or "").strip()

    return render(
        request,
        "purchase/injection/receipts/candidates.html",
        {
            "order": order,
            "order_info": order_info,
            "candidates": candidates,
            "today": now().date(),
            "rcpt_lot": rcpt_lot,
        },
    )

# ─────────────────────────────────────────────────────────────────────────────
# 선택 라인 커밋(입고확정) – 배송그룹별 헤더, 서브LOT 1:1
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@require_POST
@transaction.atomic
def receipt_commit(request, order_id):
    user = request.user
    order = get_object_or_404(InjectionOrder, pk=order_id, dlt_yn='N')

    # 날짜 정규화
    raw_receipt_date = request.POST.get("receipt_date")
    if raw_receipt_date:
        try:
            receipt_date = datetime.strptime(raw_receipt_date, "%Y-%m-%d").date()
        except Exception:
            receipt_date = _today_local()
    else:
        receipt_date = _today_local()

    remark = (request.POST.get("remark") or "").strip()

    # wh5 고정(없으면 사용가능 첫 창고)
    target_wh = (
        Warehouse.objects.filter(is_deleted="N", warehouse_id=DEFAULT_WH_CODE).first()
        or Warehouse.objects.filter(is_deleted="N").order_by("id").first()
    )
    if not target_wh:
        messages.error(request, "입고창고(wh5)를 찾을 수 없습니다.")
        return HttpResponseRedirect(reverse("purchase:inj_receipt_candidates", args=[order_id]))

    # 선택된 PASS detail 수집
    raw_ids = request.POST.getlist("detail_ids") or request.POST.get("detail_ids", "")
    if isinstance(raw_ids, str):
        raw_ids = [i for i in raw_ids.split(",") if i.strip()]
    detail_ids = [int(i) for i in raw_ids if str(i).isdigit()]
    if not detail_ids:
        messages.warning(request, "선택된 PASS 라인이 없습니다.")
        return HttpResponseRedirect(reverse("purchase:inj_receipt_candidates", args=[order_id]))

    details_qs = (
        IncomingInspectionDetail.objects
        .select_related("shipment_line__shipment")
        .filter(id__in=detail_ids, status="PASS", qty__gt=0)
    )

    # 배송그룹별 묶기
    groups = {}
    for d in details_qs:
        grp = d.shipment_line.shipment  # PartnerShipmentGroup
        if not grp:
            continue
        groups.setdefault(grp.id, []).append(d)

    if not groups:
        messages.warning(request, "입고 가능한 PASS 라인이 없습니다.")
        return HttpResponseRedirect(reverse("purchase:inj_receipt_candidates", args=[order_id]))

    created_headers = 0
    reused_headers = 0
    created_lines = 0
    total_qty_all = 0
    created_receipt_lots = []

    for grp_id, dlist in groups.items():
        grp_total = sum(int(d.qty) for d in dlist if d.qty and d.qty > 0)
        if grp_total <= 0:
            continue

        # 헤더 재사용 시도
        header = (
            InjectionReceipt.objects
            .select_for_update(skip_locked=True)
            .filter(
                order=order,
                warehouse=target_wh,
                date=receipt_date,
                shipment_group_id=grp_id,
                is_deleted=False,
            )
            .first()
        )

        header_created = False
        if header is None:
            lot_date = receipt_date
            receipt_lot = _next_receipt_lot(lot_date)

            header = InjectionReceipt.objects.create(
                order=order,
                warehouse=target_wh,
                date=receipt_date,
                receipt_lot=receipt_lot,
                qty=grp_total,
                remark=remark,
                shipment_group_id=grp_id,
                created_by=user,
            )
            header_created = True
            created_headers += 1
            created_receipt_lots.append(receipt_lot)
        else:
            reused_headers += 1

        existing_detail_ids = set(
            InjectionReceiptLine.objects
            .filter(detail_id__in=[d.id for d in dlist])
            .values_list("detail_id", flat=True)
        )

        # 서브 LOT 생성
        for d in dlist:
            if d.id in existing_detail_ids:
                continue
            if not d.qty or d.qty <= 0:
                continue

            header = (
                InjectionReceipt.objects
                .select_for_update(skip_locked=True)
                .get(pk=header.pk)
            )
            max_seq = (
                InjectionReceiptLine.objects
                .filter(receipt=header)
                .aggregate(m=Max("sub_seq"))["m"]
            ) or 0
            sub_seq = max_seq + 1
            sub_lot = f"{header.receipt_lot}-{sub_seq:02d}"

            InjectionReceiptLine.objects.create(
                receipt=header,
                sub_seq=sub_seq,
                sub_lot=sub_lot,
                qty=d.qty,
                detail=d,
            )
            created_lines += 1

        # 헤더 qty 재계산
        new_total = (
            InjectionReceiptLine.objects
            .filter(receipt=header)
            .aggregate(s=Sum("qty"))["s"]
        ) or 0

        if new_total <= 0:
            if header_created:
                header.delete()
                created_headers -= 1
                if header.receipt_lot in created_receipt_lots:
                    created_receipt_lots.remove(header.receipt_lot)
        else:
            InjectionReceipt.objects.filter(pk=header.pk).update(qty=new_total)
            total_qty_all += int(new_total)

    if created_headers or created_lines:
        msg = (
            f"입고완료 · 헤더 {created_headers}건(신규 {created_headers} · 재사용 {reused_headers}) · "
            f"라인 {created_lines}건"
        )
        if created_receipt_lots:
            msg += f" · LOT {', '.join(created_receipt_lots)}"
        messages.success(request, msg)
    else:
        messages.info(request, "변경된 입고가 없습니다. (중복 처리 또는 유효 라인 없음)")

    return HttpResponseRedirect(reverse("purchase:inj_receipt_candidates", args=[order_id]))

# ─────────────────────────────────────────────────────────────────────────────
# 선택 라인 입고 취소 – 서브 LOT 단위
# ─────────────────────────────────────────────────────────────────────────────

@require_http_methods(["POST"])
@transaction.atomic
def receipt_revert(request, order_id):
    """
    ✅ 서브 LOT(라인) 단위 입고 취소
    - rl_id(단건) 또는 rl_ids[](복수) 지원
    - 헤더 qty 재계산, 남은 라인이 0이면 헤더 삭제
    """
    # 파라미터 파싱
    ids = []
    one = request.POST.get("rl_id")
    if one and str(one).isdigit():
        ids.append(int(one))
    ids += [int(x) for x in request.POST.getlist("rl_ids") if str(x).isdigit()]
    ids = list(dict.fromkeys(ids))  # 중복 제거

    if not ids:
        messages.warning(request, "취소할 라인이 선택되지 않았습니다.")
        return redirect("purchase:inj_receipt_candidates", order_id=order_id)

    # 대상 라인 잠금
    lines = (
        InjectionReceiptLine.objects
        .select_for_update()
        .select_related("receipt")
        .filter(id__in=ids, receipt__order_id=order_id)
    )
    if not lines.exists():
        messages.warning(request, "취소 대상 라인을 찾을 수 없습니다.")
        return redirect("purchase:inj_receipt_candidates", order_id=order_id)

    affected = {}
    count = 0
    for rl in lines:
        rid = rl.receipt_id
        affected.setdefault(rid, 0)
        affected[rid] += int(rl.qty or 0)
        rl.delete()
        count += 1

    # 헤더 정리
    for rid in list(affected.keys()):
        remain = (InjectionReceiptLine.objects
                  .filter(receipt_id=rid)
                  .aggregate(s=Sum("qty"))["s"]) or 0
        if remain == 0:
            InjectionReceipt.objects.filter(id=rid).delete()
        else:
            InjectionReceipt.objects.filter(id=rid).update(qty=remain)

    messages.success(request, f"입고취소 완료 · {count} 라인")
    return redirect("purchase:inj_receipt_candidates", order_id=order_id)
