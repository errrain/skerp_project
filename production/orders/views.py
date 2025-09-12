# production/orders/views.py
# ============================================================================
# 작업지시(Production Orders) 뷰 모듈
# - 목록(무페이징/일자별)
# - 등록(라인별 저장, LOT 프로시저 호출)
# - 수정
# - 소프트 삭제
# - 수주 검색(AJAX, 기본기간 적용)
# - 목록 행 인라인 저장(AJAX: 투입행거수/생산량) + 하루 재계산
# - 순서 저장 + 스케줄 재계산(AJAX)
# - 타임존/날짜 유틸 통일(naive/aware 안전 처리)
# ============================================================================

import logging
import calendar
from datetime import datetime, date, time, timedelta

from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET, require_POST

# 외부 앱 모델
from vendor.models import Vendor
from product.models import Product
from sales.models import CustomerOrderItem

# LOT 발급 헬퍼(DB 프로시저 next_lot_seq 호출)
from utils.lot import get_next_lot

# 현재 앱
from production.models import WorkOrder, WorkOrderLine
from ..forms import WorkOrderForm, WorkOrderLineFormSet

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# 상수 / 타임 유틸
# ──────────────────────────────────────────────────────────────────────────────

# 설비 고정 행거 간격: 4분 30초 (270초)
HANGER_INTERVAL_SEC = 4 * 60 + 30


def _ensure_aware(dt: datetime | None) -> datetime | None:
    """naive datetime -> 현재 타임존 aware 로 변환 (USE_TZ=True일 때만)"""
    if not dt:
        return dt
    if getattr(settings, "USE_TZ", False) and timezone.is_naive(dt):
        return timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


def _parse_local_dt(s: str | None) -> datetime | None:
    """
    'YYYY-MM-DD HH:MM' 또는 ISO8601 문자열을 datetime으로 파싱.
    - 공백 구분이면 'T'로 치환 후 fromisoformat 적용
    - 반환 시 환경에 맞게 aware 보정
    """
    if not s:
        return None
    s = s.strip()
    if " " in s and "T" not in s:
        s = s.replace(" ", "T")
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        return None
    return _ensure_aware(dt)


def _today_localdate() -> date:
    """
    오늘 날짜를 안전하게 반환.
    - USE_TZ=True  : aware now 기반 localdate
    - USE_TZ=False : 시스템 로컬 날짜(date.today())
    """
    if getattr(settings, "USE_TZ", False):
        return timezone.localdate(timezone.now())
    return date.today()


def _day_range_for(d: date) -> tuple[datetime, datetime]:
    """[d 00:00, d+1 00:00) 구간을 환경에 맞게 aware/naive로 반환"""
    start = datetime.combine(d, time.min)
    end = start + timedelta(days=1)
    if getattr(settings, "USE_TZ", False):
        tz = timezone.get_current_timezone()
        start = timezone.make_aware(start, tz)
        end = timezone.make_aware(end, tz)
    return start, end


def _to_local_date(dt: datetime | None) -> date:
    """datetime -> 로컬 날짜 (aware/naive 모두 안전)"""
    if not dt:
        return _today_localdate()
    if getattr(settings, "USE_TZ", False):
        return timezone.localtime(dt).date()
    return dt.date()


def _month_range(d: date) -> tuple[date, date]:
    """해당 월의 [1일, 말일]"""
    first = d.replace(day=1)
    last = date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])
    return first, last


def _safe_date(s: str | None) -> date | None:
    """문자열 날짜 안전 파싱(None/빈문자 허용)"""
    return parse_date(s) if s else None


# ──────────────────────────────────────────────────────────────────────────────
# POST 정규화 + 라인 합계 산출
# ──────────────────────────────────────────────────────────────────────────────
def _normalize_and_sum(request_post, prefix="lines"):
    """
    - 템플릿 오타 키 'rack_caty' → 'rack_capacity' 보정
    - planned_start / planned_end: 문자열 → ISO8601 문자열(aware 보정)
    - 합계 수량 = Σ(라인별 rack_count × rack_capacity)
    """
    data = request_post.copy()

    # 1) 오타 보정
    to_fix = [k for k in list(data.keys()) if k.startswith(prefix + "-") and k.endswith("rack_caty")]
    for k in to_fix:
        fixed = k.replace("rack_caty", "rack_capacity")
        data.setlist(fixed, data.getlist(k))
        del data[k]

    # 2) 날짜 문자열 보정
    def _norm_dt_str(s: str) -> str:
        if not s:
            return ""
        s = s.strip()
        if " " in s and "T" not in s:
            s = s.replace(" ", "T")
        try:
            dt = datetime.strptime(s, "%Y-%m-%dT%H:%M")
        except Exception:
            try:
                dt = datetime.fromisoformat(s)
            except Exception:
                logger.warning("[시간파싱실패] value=%r -> 원문 유지", s)
                return s
        dt = _ensure_aware(dt)
        return (timezone.localtime(dt).isoformat()
                if getattr(settings, "USE_TZ", False) else dt.isoformat())

    for key in ("planned_start", "planned_end"):
        if key in data:
            data[key] = _norm_dt_str(data.get(key))

    # 3) 합계
    def _to_i(v):
        try:
            return int((v or "0").replace(",", ""))
        except Exception:
            return 0

    total = 0
    total_forms = _to_i(data.get(f"{prefix}-TOTAL_FORMS", "0"))
    for i in range(total_forms):
        if data.get(f"{prefix}-{i}-DELETE") in ("on", "true", "True", "1"):
            continue
        rcount = _to_i(data.get(f"{prefix}-{i}-rack_count"))
        rcap = _to_i(data.get(f"{prefix}-{i}-rack_capacity"))
        total += rcount * rcap

    return data, total


# ──────────────────────────────────────────────────────────────────────────────
# 순서 저장 + 스케줄 재계산 (AJAX)
# ──────────────────────────────────────────────────────────────────────────────
@require_POST
@transaction.atomic
def order_reorder(request):
    """
    ids[]=... 순서대로 당일 스케줄을 재배치.
    - 앵커: 선택 집합의 최소 planned_start
    - 소요시간: (라인의 투입행거수 × 4:30)
    - 완료 후 각 행의 최신 start/end 반환
    """
    ids = request.POST.getlist("ids[]")
    if not ids:
        return JsonResponse({"ok": False, "msg": "변경할 항목이 없습니다."})

    wos = list(WorkOrder.all_objects.filter(pk__in=ids))
    if len(wos) != len(ids):
        return JsonResponse({"ok": False, "msg": "일부 항목을 찾을 수 없습니다."})

    base_date = _to_local_date(wos[0].planned_start)
    anchor = min((wo.planned_start for wo in wos if wo.planned_start), default=None)
    if not anchor:
        anchor, _ = _day_range_for(base_date)

    wo_map = {wo.id: wo for wo in wos}
    cur = anchor

    for i, sid in enumerate(ids):
        wo = wo_map.get(int(sid))
        if not wo:
            continue
        line = (WorkOrderLine.all_objects.filter(work_order=wo).order_by("id").first())
        hcnt = int(getattr(line, "hanger_count", 0) or 0)

        duration = timedelta(seconds=hcnt * HANGER_INTERVAL_SEC)
        wo.planned_start = cur
        wo.planned_end = cur + duration
        wo.save(update_fields=["planned_start", "planned_end"])

        if line and line.sequence != i + 1:
            line.sequence = i + 1
            line.save(update_fields=["sequence"])

        cur = wo.planned_end

    _recalc_day_schedule(base_date)

    def _fmt(dt):
        if not dt:
            return ""
        return (timezone.localtime(dt).strftime("%Y-%m-%d %H:%M")
                if getattr(settings, "USE_TZ", False) else dt.strftime("%Y-%m-%d %H:%M"))

    refreshed = WorkOrder.all_objects.filter(pk__in=ids)
    payload = {str(wo.id): {"start": _fmt(wo.planned_start), "end": _fmt(wo.planned_end)} for wo in refreshed}
    return JsonResponse({"ok": True, "times": payload, "msg": "순서 저장 및 재계산 완료"})


# ──────────────────────────────────────────────────────────────────────────────
# 하루 스케줄 재계산 (고정 행거간격 4:30)
# ──────────────────────────────────────────────────────────────────────────────
@transaction.atomic
def _recalc_day_schedule(base_date: date):
    """
    base_date의 모든 WorkOrder를 planned_start 오름차순으로 정렬한 뒤,
    WorkOrderLine.hanger_count × 4:30 만큼의 소요 시간을 앞에서 뒤로 누적 반영.
    """
    start_dt, end_dt = _day_range_for(base_date)
    qs = (WorkOrder.all_objects
          .filter(planned_start__gte=start_dt, planned_start__lt=end_dt)
          .select_related("product", "customer")
          .order_by("planned_start", "created_at", "id"))

    if not qs.exists():
        return

    cur = qs.first().planned_start
    for wo in qs:
        line = (WorkOrderLine.all_objects.filter(work_order=wo).order_by("id").first())
        hcnt = int(getattr(line, "hanger_count", 0) or 0)
        duration = timedelta(seconds=hcnt * HANGER_INTERVAL_SEC)

        wo.planned_start = cur
        wo.planned_end = cur + duration
        wo.save(update_fields=["planned_start", "planned_end"])

        cur = wo.planned_end


# ──────────────────────────────────────────────────────────────────────────────
# 목록 (무페이징, 기본=오늘)
# ──────────────────────────────────────────────────────────────────────────────
def order_list(request):
    """선택 일자의 작업지시 목록(무페이징, 상하 이동/시간조정 UI 전제)"""
    try:
        d_str = (request.GET.get("d") or "").strip()
        query_date = datetime.strptime(d_str, "%Y-%m-%d").date() if d_str else _today_localdate()
    except Exception:
        query_date = _today_localdate()

    start_dt, end_dt = _day_range_for(query_date)

    q = (request.GET.get("q") or "").strip()
    qs = WorkOrder.objects.filter(planned_start__gte=start_dt, planned_start__lt=end_dt)
    if q:
        qs = qs.filter(
            Q(product__name__icontains=q) |
            Q(customer__name__icontains=q) |
            Q(work_lot__icontains=q)
        )
    qs = qs.select_related("product", "customer").order_by("planned_start", "created_at", "id")

    ctx = {
        "orders": qs,
        "keyword": q,
        "query_date": query_date,
        "prev_date": query_date - timedelta(days=1),
        "next_date": query_date + timedelta(days=1),
    }
    return render(request, "production/orders/order_list.html", ctx)


def get_last_end(request):
    """
    최근 작업지시의 계획 시간과 표시용 요약 정보를 반환.
    """
    qs = WorkOrder.objects.all()
    if hasattr(WorkOrder, 'dlt_yn'):
        qs = qs.filter(dlt_yn='N')
    qs = qs.exclude(planned_end__isnull=True).order_by('-planned_end')

    wo = qs.select_related('product','customer').prefetch_related('lines').first()
    if not wo:
        return JsonResponse({
            "last_end": None, "last_start": None, "lot": None,
            "product_name": None, "customer_name": None,
            "hanger_count": 0, "prod_qty": 0,
        })

    def _fmt(dt):
        if not dt: return None
        dt = timezone.localtime(dt) if timezone.is_aware(dt) else dt
        return dt.strftime("%Y-%m-%d %H:%M")

    # 대표 라인 1개 선택 정책(마지막 라인 기준 예시)
    line_qs = getattr(wo, 'lines', None)
    line = line_qs.order_by('-id').first() if line_qs else None

    hanger_count = getattr(line, 'hanger_count', 0) or 0
    cap_hanger   = getattr(line, 'hanger_capacity', 0) or 0
    cap_rack     = getattr(line, 'rack_capacity', 0) or 0
    prod_qty     = hanger_count * cap_hanger * cap_rack

    return JsonResponse({
        "last_end":   _fmt(wo.planned_end),
        "last_start": _fmt(wo.planned_start),
        "lot": getattr(wo, 'work_lot', None) or getattr(wo, 'lot', None),
        "product_name": getattr(getattr(wo, 'product', None), 'name', None),
        "customer_name": getattr(getattr(wo, 'customer', None), 'name', None),
        "hanger_count": hanger_count,
        "prod_qty": prod_qty,
    })


# ──────────────────────────────────────────────────────────────────────────────
# 등록
# ──────────────────────────────────────────────────────────────────────────────
@transaction.atomic
def order_create(request):
    """
    작업지시 등록(라인별 저장)
    - 라인마다 WorkOrder 1건 생성
    - 생산량 = rack_count × rack_capacity (빈행거는 0 허용)
    - 시간: start_text/end_text 우선 → 없으면 헤더값(필요 시 행거수×4:30으로 종료 보정)
    - LOT: get_next_lot('JB', anchor)
    """
    if request.method == "POST":
        # 1) POST 정규화 + 합계
        data, total_qty = _normalize_and_sum(request.POST, prefix="lines")
        if not (data.get("order_qty") or "").strip():
            data["order_qty"] = str(total_qty)

        # ── 1-1) 헤더 product/customer 비어 있으면 라인에서 보충(없으면 DUMMY로) ──
        prefix = "lines"

        def _to_pk_str(v: str | None) -> str:
            v = (v or "").strip()
            return str(int(v)) if v.isdigit() and int(v) > 0 else ""

        if not data.get("product") or not data.get("customer"):
            try:
                total_forms = int((data.get(f"{prefix}-TOTAL_FORMS") or "0").replace(",", ""))
            except Exception:
                total_forms = 0

            first_prod = ""
            first_cust = ""
            for i in range(total_forms):
                # 삭제 체크
                if data.get(f"{prefix}-{i}-DELETE") in ("on", "true", "True", "1"):
                    continue
                p = _to_pk_str(data.get(f"{prefix}-{i}-product_id"))
                c = _to_pk_str(data.get(f"{prefix}-{i}-customer_id"))
                if p and not first_prod:
                    first_prod = p
                if c and not first_cust:
                    first_cust = c
                if first_prod and first_cust:
                    break

            if not data.get("product"):
                dummy_p = getattr(settings, "DUMMY_PRODUCT_ID", None)
                if first_prod:
                    data["product"] = first_prod
                elif dummy_p:
                    data["product"] = str(dummy_p)

            if not data.get("customer"):
                dummy_c = getattr(settings, "DUMMY_CUSTOMER_ID", None)
                if first_cust:
                    data["customer"] = first_cust
                elif dummy_c:
                    data["customer"] = str(dummy_c)

        # 2) 헤더(요약) 검증
        form = WorkOrderForm(data)
        if not form.is_valid():
            logger.warning("[작업지시 등록] 헤더 폼 검증 실패 | form=%s", form.errors)
            messages.error(request, "입력값을 다시 확인하세요.")
            return redirect("orders:order_create")

        base = form.save(commit=False)
        base.created_by = request.user  # 헤더 값 참고용

        # 3) 라인 파싱/저장
        def _toi(v, d=0):
            try:
                return int((v or "0").replace(",", ""))
            except Exception:
                return d

        def _to_pk(v):
            v = (v or "").strip()
            return int(v) if v.isdigit() and int(v) > 0 else None

        total_forms = _toi(data.get(f"{prefix}-TOTAL_FORMS"), 0)
        created_ids: list[int] = []

        for idx in range(total_forms):
            # 삭제 체크
            if data.get(f"{prefix}-{idx}-DELETE") in ("on", "true", "True", "1"):
                continue

            rack_cap = max(0, _toi(data.get(f"{prefix}-{idx}-rack_capacity")))
            rack_cnt = max(0, _toi(data.get(f"{prefix}-{idx}-rack_count")))
            hang_cap = max(0, _toi(data.get(f"{prefix}-{idx}-hanger_capacity")))
            hang_cnt = max(0, _toi(data.get(f"{prefix}-{idx}-hanger_count")))
            remark   = (data.get(f"{prefix}-{idx}-remark") or "").strip()

            # ▶ 행거수가 0이면 이 라인은 스킵(시간/스케줄 차지 안함)
            if hang_cnt <= 0:
                logger.debug("[라인 스킵] idx=%s hanger_count=0", idx)
                continue

            # (a) 생산량
            line_qty = rack_cnt * rack_cap  # 빈행거면 0이 정상

            # (b) 시간: 라인 hidden 우선 → 헤더 → now, 종료 보정
            s_txt = data.get(f"{prefix}-{idx}-start_text") or ""
            e_txt = data.get(f"{prefix}-{idx}-end_text") or ""
            s_dt  = _parse_local_dt(s_txt) or _ensure_aware(base.planned_start) or timezone.now()
            e_dt  = _parse_local_dt(e_txt) or _ensure_aware(base.planned_end)
            if not e_dt or e_dt < s_dt:
                duration = timedelta(seconds=hang_cnt * HANGER_INTERVAL_SEC)
                e_dt = s_dt + duration

            # (c) 라인별 제품/고객 — 값이 유효하지 않으면 헤더로 폴백
            prod_key = f"{prefix}-{idx}-product_id"
            cust_key = f"{prefix}-{idx}-customer_id"

            prod_id = _to_pk(data.get(prod_key)) if prod_key in data else None
            if not prod_id:
                prod_id = getattr(base.product, "id", None)

            cust_id = _to_pk(data.get(cust_key)) if cust_key in data else None
            if not cust_id:
                cust_id = getattr(base.customer, "id", None)

            # (선택) DUMMY 보강
            if not prod_id:
                prod_id = getattr(settings, "DUMMY_PRODUCT_ID", None) or prod_id
            if not cust_id:
                cust_id = getattr(settings, "DUMMY_CUSTOMER_ID", None) or cust_id

            # 모델 NOT NULL 보호
            if not prod_id or not cust_id:
                logger.warning("[라인 스킵] idx=%s product/customer 비어있음(prod=%s, cust=%s)", idx, prod_id, cust_id)
                continue

            # (d) WorkOrder 생성
            wo = WorkOrder(
                product_id=prod_id,
                customer_id=cust_id,
                remark=remark or base.remark or "",
                created_by=request.user,
                order_qty=line_qty,
                planned_start=s_dt,
                planned_end=e_dt,
            )

            # LOT(작업: JB) — anchor: 라인 시작 → 헤더 → now
            anchor = s_dt or _ensure_aware(base.planned_start) or timezone.now()
            wo.work_lot = get_next_lot("JB", anchor)
            wo.save()

            # (e) WorkOrderLine 생성(연속 시퀀스)
            seq = len(created_ids) + 1
            WorkOrderLine.objects.create(
                work_order=wo,
                sequence=seq,
                rack_capacity=rack_cap,
                rack_count=rack_cnt,
                hanger_capacity=hang_cap,
                hanger_count=hang_cnt,
                remark=remark,
            )

            created_ids.append(wo.id)
            logger.debug("[라인 저장] idx=%s seq=%s wo_id=%s qty=%s start=%s end=%s",
                         idx, seq, wo.id, wo.order_qty, wo.planned_start, wo.planned_end)

        if created_ids:
            first = WorkOrder.all_objects.get(pk=created_ids[0])
            _recalc_day_schedule(_to_local_date(first.planned_start))
            messages.success(request, f"작업지시 {len(created_ids)}건 등록 완료")
            logger.info("[작업지시 등록 성공] IDs=%s", created_ids)
            return redirect("orders:order_list")

        messages.warning(request, "저장할 유효한 라인이 없습니다.")
        logger.info("[작업지시 등록] 생성된 라인 없음")
        return redirect("orders:order_create")

    # ── GET 또는 검증 실패 시: 화면 렌더 ──
    form = locals().get("form") or WorkOrderForm()
    formset = locals().get("formset") or WorkOrderLineFormSet(prefix="lines")

    # 수주 목록: 최초 진입에도 기본기간(당월 1~말일) 적용
    today = _today_localdate()
    first, last = _month_range(today)

    od_f = parse_date(request.GET.get("order_date_from") or "")
    od_t = parse_date(request.GET.get("order_date_to") or "")
    dd_f = parse_date(request.GET.get("delivery_date_from") or "")
    dd_t = parse_date(request.GET.get("delivery_date_to") or "")
    name = (request.GET.get("name") or "").strip()

    qs = (CustomerOrderItem.objects
          .select_related("order", "product", "order__customer")
          .filter(order__delete_yn="N"))

    if not (od_f or od_t or dd_f or dd_t or name):
        qs = qs.filter(order__order_date__gte=first, order__order_date__lte=last)
    else:
        if name:
            qs = qs.filter(
                Q(product__name__icontains=name) |
                Q(product__code__icontains=name) |
                Q(product__part_number__icontains=name)
            )
        if od_f:
            qs = qs.filter(order__order_date__gte=od_f)
        if od_t:
            qs = qs.filter(order__order_date__lte=od_t)
        if dd_f:
            qs = qs.filter(delivery_date__gte=dd_f)
        if dd_t:
            qs = qs.filter(delivery_date__lte=dd_t)

    sales_list = qs.order_by("-order__order_date", "-id")[:200]

    customers = Vendor.objects.order_by("name")

    customer_id = (request.GET.get("customer") or "").strip()
    q = (request.GET.get("q") or "").strip()
    product_qs = Product.objects.select_related("customer").filter(delete_yn="N", use_yn="Y")
    if customer_id:
        product_qs = product_qs.filter(customer_id=customer_id)
    if q:
        product_qs = product_qs.filter(
            Q(name__icontains=q) | Q(part_number__icontains=q) | Q(alias__icontains=q)
        )
    search_results = product_qs.order_by("customer__name", "name")[:50]
    minute_choices = [f"{i:02d}" for i in range(60)]

    return render(request, "production/orders/order_form.html", {
        "form": form,
        "formset": formset,
        "sales_list": sales_list,
        "customers": customers,
        "selected_customer": customer_id,
        "query": q,
        "search_results": search_results,
        "minute_choices": minute_choices,
        "order_date_from": (od_f or first).strftime("%Y-%m-%d"),
        "order_date_to": (od_t or last).strftime("%Y-%m-%d"),
        "delivery_date_from": (dd_f or first).strftime("%Y-%m-%d"),
        "delivery_date_to": (dd_t or last).strftime("%Y-%m-%d"),
    })


# ──────────────────────────────────────────────────────────────────────────────
# 수정
# ──────────────────────────────────────────────────────────────────────────────
@transaction.atomic
def order_edit(request, pk):
    work_order = get_object_or_404(WorkOrder, pk=pk)

    if request.method == "POST":
        data, total_qty = _normalize_and_sum(request.POST, prefix="lines")
        if not (data.get("order_qty") or "").strip():
            data["order_qty"] = str(total_qty)

        form = WorkOrderForm(data, instance=work_order)
        provisional_parent = form.instance
        provisional_parent.order_qty = total_qty
        formset = WorkOrderLineFormSet(data, instance=provisional_parent, prefix="lines")

        if form.is_valid() and formset.is_valid():
            wo = form.save(commit=False)
            wo.order_qty = total_qty
            wo.planned_start = _ensure_aware(wo.planned_start)
            wo.planned_end = _ensure_aware(wo.planned_end)
            wo.save()
            formset.save()

            _recalc_day_schedule(_to_local_date(wo.planned_start))
            messages.success(request, f"작업지시서 {wo.work_lot} 수정 완료")
            return redirect("orders:order_list")
    else:
        form = WorkOrderForm(instance=work_order)
        formset = WorkOrderLineFormSet(instance=work_order, prefix="lines")

    minute_choices = [f"{i:02d}" for i in range(60)]
    return render(request, "production/orders/order_form.html", {
        "form": form,
        "formset": formset,
        "work_order": work_order,
        "minute_choices": minute_choices,
    })


# ──────────────────────────────────────────────────────────────────────────────
# 삭제(소프트)
# ──────────────────────────────────────────────────────────────────────────────
@require_POST
@transaction.atomic
def order_delete(request, pk: int):
    o = get_object_or_404(WorkOrder.all_objects, pk=pk)
    base_date = _to_local_date(o.planned_start)
    o.soft_delete()
    _recalc_day_schedule(base_date)  # 삭제 후에도 일자 정렬 유지
    messages.success(request, f"[{o.work_lot}] 삭제(숨김) 완료")
    return redirect("orders:order_list")


# ──────────────────────────────────────────────────────────────────────────────
# 수주 검색 (AJAX)
# ──────────────────────────────────────────────────────────────────────────────
@require_GET
def search_sales_orders(request):
    """
    수주 검색 API.
    - 파라미터가 전혀 없으면: 당월 1~말일(수주일) 기본 적용
    - name: 품명/코드/PartNo 부분 일치
    - order_date_from/to, delivery_date_from/to: 범위 필터
    """
    name = (request.GET.get("name") or "").strip()
    od_f = _safe_date(request.GET.get("order_date_from"))
    od_t = _safe_date(request.GET.get("order_date_to"))
    dd_f = _safe_date(request.GET.get("delivery_date_from"))
    dd_t = _safe_date(request.GET.get("delivery_date_to"))

    qs = CustomerOrderItem.objects.select_related("order", "product", "order__customer")

    none_given = not (name or od_f or od_t or dd_f or dd_t)
    if none_given:
        first, last = _month_range(_today_localdate())
        qs = qs.filter(order__order_date__gte=first, order__order_date__lte=last)
    else:
        if name:
            qs = qs.filter(
                Q(product__name__icontains=name) |
                Q(product__code__icontains=name) |
                Q(product__part_number__icontains=name)
            )
        if od_f:
            qs = qs.filter(order__order_date__gte=od_f)
        if od_t:
            qs = qs.filter(order__order_date__lte=od_t)
        if dd_f:
            qs = qs.filter(delivery_date__gte=dd_f)
        if dd_t:
            qs = qs.filter(delivery_date__lte=dd_t)

    qs = qs.order_by("-order__order_date", "-id")[:200]

    results = [
        {
            "item_id": it.id,
            "order_id": it.order_id,
            "order_date": it.order.order_date.strftime("%Y-%m-%d") if it.order.order_date else "",
            "planned_ship_date": it.delivery_date.strftime("%Y-%m-%d") if it.delivery_date else "",
            "customer_id": it.order.customer_id,
            "customer_name": getattr(it.order.customer, "name", ""),
            "product_id": it.product_id,
            "product_code": (getattr(it.product, "code", "") or getattr(it.product, "part_number", "")) or "",
            "product_name": getattr(it.product, "name", ""),
            "order_qty": it.quantity or 0,
            "injection_stock": None,
        }
        for it in qs
    ]

    return JsonResponse({
        "ok": True,
        "count": len(results),
        "filters": {
            "name": name,
            "order_date_from": od_f.isoformat() if od_f else None,
            "order_date_to": od_t.isoformat() if od_t else None,
            "delivery_date_from": dd_f.isoformat() if dd_f else None,
            "delivery_date_to": dd_t.isoformat() if dd_t else None,
            "default_month_applied": none_given,
        },
        "results": results,
    })


# ──────────────────────────────────────────────────────────────────────────────
# 목록 행 인라인 저장 (AJAX) + 하루 재계산
# ──────────────────────────────────────────────────────────────────────────────
@require_POST
@transaction.atomic
def order_row_update(request, pk: int):
    """
    한 행 인라인 편집 저장:
      - 투입행거수(WorkOrderLine.hanger_count)
      - 생산량(WorkOrder.order_qty) = 투입행거수 × 행거당 렉수량 × 렉당 제품수
    저장 후 해당 날짜 전체를 4:30 기준으로 다시 배치.
    """
    wo = get_object_or_404(WorkOrder.all_objects.select_related(), pk=pk)

    def _to_i(v, default=0):
        try:
            return int((v or "").replace(",", ""))
        except Exception:
            return default

    new_hcnt = _to_i(request.POST.get("hanger_count"), 0)

    line = (WorkOrderLine.all_objects.filter(work_order=wo).order_by("id").first())
    if not line:
        return JsonResponse({"ok": False, "msg": "라인 정보가 없습니다."})

    # 라인 업데이트
    line.hanger_count = max(0, new_hcnt)
    line.save(update_fields=["hanger_count"])

    # 생산량 재계산 = 투입행거수 × 행거당 렉수량 × 렉당 제품수
    hcnt = int(line.hanger_count or 0)
    hcap = int(line.hanger_capacity or 0)
    rcap = int(line.rack_capacity or 0)
    calc_qty = max(0, hcnt * hcap * rcap)

    wo.order_qty = calc_qty
    wo.save(update_fields=["order_qty"])

    base_date = _to_local_date(wo.planned_start)
    _recalc_day_schedule(base_date)

    wo = WorkOrder.all_objects.get(pk=wo.pk)

    def _fmt(dt):
        if not dt:
            return ""
        return (timezone.localtime(dt).strftime("%Y-%m-%d %H:%M")
                if getattr(settings, "USE_TZ", False) else dt.strftime("%Y-%m-%d %H:%M"))

    return JsonResponse({
        "ok": True,
        "work_order_id": wo.id,
        "hanger_count": hcnt,
        "order_qty": calc_qty,
        "planned_start": _fmt(wo.planned_start),
        "planned_end": _fmt(wo.planned_end),
        "msg": "저장 및 하루 스케줄 재계산 완료",
    })
