# quality/views.py
from __future__ import annotations

import csv
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from typing import Dict, Optional

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import (
    Case,
    CharField,
    DateTimeField,
    OuterRef,
    Prefetch,
    Subquery,
    Sum,
    Value,
    When,
)
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from injectionorder.models import InjectionOrder, FlowStatus

# 검사 헤더 + 라인
from .inspections.models import (
    IncomingInspection,
    IncomingInspectionDetail,
    QCStatus,
    DEFECT_CODE_CHOICES,
)

# 배송상세(그룹) + 라인 + 박스
from partnerorder.models import (
    PartnerShipmentGroup,
    PartnerShipmentLine,
    PartnerShipmentBox,
)

import logging

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# 유틸
# ─────────────────────────────────────────────────────────────────────────────

def _to_date_or_none(s: Optional[str]) -> Optional[date]:
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date() if s else None
    except Exception:
        return None


def _to_int_or_zero(s: Optional[str]) -> int:
    try:
        return int(s) if s not in (None, "") else 0
    except Exception:
        return 0


# 검사 모델에 배송상세 식별자 컬럼(정수)이 존재하는지: 마이그레이션 과도기 안전장치
HAS_SHIPMENT_FIELD: bool = any(
    getattr(f, "name", None) == "shipment_id" for f in IncomingInspection._meta.get_fields()
)


def _latest_inspection(order: InjectionOrder, shipment_id: Optional[int]) -> Optional[IncomingInspection]:
    """주문(+선택 배송상세)에 대한 최신 검사 1건."""
    qs = IncomingInspection.objects.filter(order=order)
    if HAS_SHIPMENT_FIELD and shipment_id is not None:
        qs = qs.filter(shipment_id=shipment_id)
    return qs.order_by("-created_at", "-id").first()


def _aggregate_status_from_latest_per_shipment(order: InjectionOrder) -> tuple[str, Optional[datetime]]:
    """
    주문에 대해 '배송상세별 최신 검사'를 모아 집계 상태/최신시각 계산.
      - 아무 검사도 없으면  → '미실시'
      - 전부 PASS          → '합격'
      - PASS + (그 외) 공존 → '부분합격'
      - PASS 없음 & FAIL만 → '불합격'
      - PASS 없음 & HOLD만 → '보류'
      - 그 외               → '대기'
    """
    insp_list = list(
        IncomingInspection.objects.filter(order=order)
        .order_by("shipment_id", "-created_at", "-id")
        .only("shipment_id", "status", "created_at")
    )
    latest_by_ship: Dict[Optional[int], IncomingInspection] = {}
    for ii in insp_list:
        sid = getattr(ii, "shipment_id", None)
        if sid not in latest_by_ship:
            latest_by_ship[sid] = ii

    if not latest_by_ship:
        return ("미실시", None)

    statuses = {ii.status for ii in latest_by_ship.values()}
    last_dt = max(ii.created_at for ii in latest_by_ship.values())

    if statuses == {QCStatus.PASS}:
        return ("합격", last_dt)
    if QCStatus.PASS in statuses and (statuses - {QCStatus.PASS}):
        return ("부분합격", last_dt)
    if QCStatus.FAIL in statuses and QCStatus.PASS not in statuses and QCStatus.HOLD not in statuses and QCStatus.DRAFT not in statuses:
        return ("불합격", last_dt)
    if QCStatus.HOLD in statuses and QCStatus.PASS not in statuses:
        return ("보류", last_dt)
    if statuses == {QCStatus.DRAFT}:
        return ("대기", last_dt)
    return ("대기", last_dt)


# ─────────────────────────────────────────────────────────────────────────────
# 목록 / 엑셀
# ─────────────────────────────────────────────────────────────────────────────

def incoming_list(request):
    qs = (
        InjectionOrder.objects
        .filter(flow_status__in=[FlowStatus.PRT, FlowStatus.RCV], dlt_yn="N")
        .select_related("vendor")
        .prefetch_related("items")
        .annotate(qty_sum=Sum("items__quantity"))
        .order_by("-order_date", "-id")
        .distinct()
    )

    # ─────────────────────────────────────────────
    # 🔍 GET 파라미터 로드
    # ─────────────────────────────────────────────
    order_date_start = (request.GET.get("order_date_start") or "").strip()
    order_date_end = (request.GET.get("order_date_end") or "").strip()
    expected_date_start = (request.GET.get("expected_date_start") or "").strip()
    expected_date_end = (request.GET.get("expected_date_end") or "").strip()
    vendor_name = (request.GET.get("vendor") or "").strip()
    product_name = (request.GET.get("product") or "").strip()

    # 🔽 GET 파라미터가 완전히 비어 있으면 → 기본값: 최근 7일
    if not any([order_date_start, order_date_end, expected_date_start, expected_date_end, vendor_name, product_name]):
        today = date.today()
        one_week_ago = today - timedelta(days=7)
        order_date_start = one_week_ago.strftime("%Y-%m-%d")
        order_date_end = today.strftime("%Y-%m-%d")

    # ─────────────────────────────────────────────
    # 검색 필터 적용
    # ─────────────────────────────────────────────
    if order_date_start:
        qs = qs.filter(order_date__gte=order_date_start)
    if order_date_end:
        qs = qs.filter(order_date__lte=order_date_end)
    if expected_date_start:
        qs = qs.filter(due_date__gte=expected_date_start)
    if expected_date_end:
        qs = qs.filter(due_date__lte=expected_date_end)
    if vendor_name:
        qs = qs.filter(vendor__name__icontains=vendor_name)
    if product_name:
        qs = qs.filter(items__injection__name__icontains=product_name)

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get("page") or 1)

    # 집계 상태
    for o in page_obj.object_list:
        status_disp, last_dt = _aggregate_status_from_latest_per_shipment(o)
        o.insp_status_display = status_disp
        o.insp_date = last_dt

    q = request.GET.copy()
    q.pop("page", None)
    querystring = q.urlencode()

    return render(
        request,
        "quality/incoming/list.html",
        {
            "orders": page_obj.object_list,
            "page_obj": page_obj,
            "querystring": querystring,

            # ⬇️ 템플릿에서 input 기본값 유지용
            "order_date_start": order_date_start,
            "order_date_end": order_date_end,
            "expected_date_start": expected_date_start,
            "expected_date_end": expected_date_end,
        },
    )


@require_http_methods(["GET"])
def incoming_export(request):
    """수입검사 목록 CSV 다운로드(동일 필터/정렬)."""
    qs = (
        InjectionOrder.objects
        .filter(flow_status__in=[FlowStatus.PRT, FlowStatus.RCV], dlt_yn="N")
        .select_related("vendor")
        .prefetch_related("items")
        .annotate(qty_sum=Sum("items__quantity"))
        .order_by("-order_date", "-id")
        .distinct()
    )

    # 동일 검색
    order_date_start = (request.GET.get("order_date_start") or "").strip()
    order_date_end = (request.GET.get("order_date_end") or "").strip()
    expected_date_start = (request.GET.get("expected_date_start") or "").strip()
    expected_date_end = (request.GET.get("expected_date_end") or "").strip()
    vendor_name = (request.GET.get("vendor") or "").strip()
    product_name = (request.GET.get("product") or "").strip()

    if order_date_start:
        qs = qs.filter(order_date__gte=order_date_start)
    if order_date_end:
        qs = qs.filter(order_date__lte=order_date_end)
    if expected_date_start:
        qs = qs.filter(due_date__gte=expected_date_start)
    if expected_date_end:
        qs = qs.filter(due_date__lte=expected_date_end)
    if vendor_name:
        qs = qs.filter(vendor__name__icontains=vendor_name)
    if product_name:
        qs = qs.filter(items__injection__name__icontains=product_name)

    resp = HttpResponse(content_type="text/csv; charset=utf-8-sig")
    resp["Content-Disposition"] = 'attachment; filename="incoming_list.csv"'
    w = csv.writer(resp)
    w.writerow(["발주LOT", "발주처", "발주일", "품명(대표)", "수량합", "입고예정일", "진행상태", "수입검사상태", "검사시각"])

    for o in qs:
        status_disp, last_dt = _aggregate_status_from_latest_per_shipment(o)
        first = o.items.first()
        item_name = first.injection.name if first and first.injection else "-"
        w.writerow([
            o.order_lot,
            o.vendor.name if o.vendor else "-",
            o.order_date.strftime("%Y-%m-%d") if o.order_date else "-",
            item_name,
            o.qty_sum or 0,
            o.due_date.strftime("%Y-%m-%d") if o.due_date else "-",
            o.get_flow_status_display(),
            status_disp,
            last_dt.strftime("%Y-%m-%d %H:%M") if last_dt else "-",
        ])
    return resp


# ─────────────────────────────────────────────────────────────────────────────
# 배송상세 반복(검사 입력)
# ─────────────────────────────────────────────────────────────────────────────

@require_http_methods(["GET"])
def incoming_inspect_layer(request, order_id: int):
    order = get_object_or_404(
        InjectionOrder.objects
        .select_related("vendor")
        .prefetch_related("items__injection"),
        pk=order_id
    )

    qty_sum = order.items.aggregate(s=Sum("quantity"))["s"] or 0
    shipped_sum = (
        PartnerShipmentBox.objects
        .filter(group__order=order, dlt_yn="N", group__dlt_yn="N")
        .aggregate(s=Sum("qty"))["s"] or 0
    )
    remain = max(0, qty_sum - shipped_sum)

    first_item = order.items.first()
    product_name = first_item.injection.name if first_item and first_item.injection else "-"

    show_cancel = (request.GET.get("show_cancel") == "1")
    grp_qs = PartnerShipmentGroup.objects.filter(order=order)
    if not show_cancel:
        grp_qs = grp_qs.filter(dlt_yn="N")

    # 라인/박스 프리패치
    grp_qs = grp_qs.prefetch_related(
        Prefetch("items", queryset=PartnerShipmentLine.objects.filter(dlt_yn="N").order_by("sub_seq")),
        "boxes",
    ).order_by("group_no", "id")

    shipments = []
    for grp in grp_qs:
        # 배송일: ship_date 없으면 created_at 사용
        shipping_dt = getattr(grp, "ship_date", None) or getattr(grp, "created_at", None)
        if isinstance(shipping_dt, datetime):
            shipping_str = shipping_dt.strftime("%Y-%m-%d %H:%M")
        elif isinstance(shipping_dt, date):
            shipping_str = shipping_dt.strftime("%Y-%m-%d")
        else:
            shipping_str = None

        # ✅ 사출일(제조일) = PartnerShipmentGroup.inject_date
        inject_dt = getattr(grp, "inject_date", None)
        if isinstance(inject_dt, datetime):
            inject_str = inject_dt.strftime("%Y-%m-%d")
        elif isinstance(inject_dt, date):
            inject_str = inject_dt.strftime("%Y-%m-%d")
        else:
            inject_str = None

        # ✅ 협력사 제조일: production_date 사용 (Date / DateTime 모두 대응)
        production_dt = getattr(grp, "production_date", None)
        if isinstance(production_dt, datetime):
            production_str = production_dt.strftime("%Y-%m-%d %H:%M")
        elif isinstance(production_dt, date):
            production_str = production_dt.strftime("%Y-%m-%d")
        else:
            production_str = None

        # 라인 우선, 없으면 박스 기준
        if hasattr(grp, "items") and grp.items.exists():
            total_qty = sum(l.qty for l in grp.items.all())
            tokens = [f"{grp.group_no}-{l.sub_seq} : {l.qty}" for l in grp.items.all()]
        else:
            alive_boxes = [b for b in grp.boxes.all() if b.dlt_yn == "N"]
            total_qty = sum(b.qty for b in alive_boxes)
            tokens = [f"{grp.group_no}-{b.box_no} : {b.qty}" for b in alive_boxes]

        insp = _latest_inspection(order, grp.id) if HAS_SHIPMENT_FIELD else None
        insp_dict = None
        if insp:
            insp_dict = {
                "inspection_date": insp.inspection_date,
                "status": insp.status,
                "defects": insp.defects or [],
                "inspect_qty": insp.inspect_qty,
                "return_qty": insp.return_qty,
                "remark": insp.remark,
            }

        shipments.append(SimpleNamespace(
            id=getattr(grp, "id", None),
            seq=getattr(grp, "group_no", None) or "-",
            shipping_str=shipping_str,          # 기존
            production_str=production_str,      # ✅ 추가
            inject_str=inject_str,  # ✅ 여기 추가
            total_qty=total_qty,
            tokens=tokens,
            is_cancelled=(getattr(grp, "dlt_yn", "N") == "Y"),
            cancel_at=getattr(grp, "updated_at", None),
            insp=insp_dict,
        ))

    ctx = {
        "order": order,
        "qty_sum": qty_sum,
        "product_name": product_name,
        "shipments": shipments,
        "status_choices": QCStatus.choices,
        "defect_choices": DEFECT_CODE_CHOICES,
        "today": date.today(),
        "show_cancel": show_cancel,
        "shipped_sum": shipped_sum,
        "remain": remain,
    }
    return render(request, "quality/incoming/inspect_modal.html", ctx)


@require_http_methods(["POST"])
def incoming_inspect_save(request, order_id: int):
    """
    저장 버튼 → 검사 헤더 1건 + (존재 시) 배송상세 하위 라인 수만큼 검사 라인 스냅 자동 생성
    - 라인이 아직 없다면 헤더만 저장(박스 합 기준으로 검증)
    """
    order = get_object_or_404(
        InjectionOrder.objects.select_related("vendor").prefetch_related("items"),
        pk=order_id,
    )

    shipment_id_raw = (request.POST.get("shipment_id") or "").strip()
    shipment_id = int(shipment_id_raw) if shipment_id_raw.isdigit() else None

    inspection_date = _to_date_or_none(request.POST.get("inspection_date"))
    status = (request.POST.get("status") or "").strip()
    defects = request.POST.getlist("defects")
    inspect_qty = _to_int_or_zero(request.POST.get("inspect_qty"))
    return_qty = _to_int_or_zero(request.POST.get("return_qty"))
    remark = (request.POST.get("remark") or "").strip()

    # 배송상세 + 라인/박스 로드
    shipment = get_object_or_404(PartnerShipmentGroup, pk=shipment_id)
    lines = list(PartnerShipmentLine.objects.filter(shipment=shipment, dlt_yn="N").order_by("id"))
    boxes = list(PartnerShipmentBox.objects.filter(group=shipment, dlt_yn="N").order_by("id"))

    # 검증 기준 합계(라인 있으면 라인, 없으면 박스 합)
    ref_total = sum(l.qty for l in lines) if lines else sum(b.qty for b in boxes)

    errors = []
    if not inspection_date:
        errors.append("검사일은 필수입니다.")
    if not status:
        errors.append("검사 상태는 필수입니다.")
    if inspect_qty < 0:
        errors.append("검사 수량은 음수가 될 수 없습니다.")
    if return_qty < 0:
        errors.append("반출(반품) 수량은 음수가 될 수 없습니다.")
    if inspect_qty > ref_total:
        errors.append(f"검사 수량({inspect_qty})이 해당 배송상세 수량합({ref_total})을 초과할 수 없습니다.")
    if status in (QCStatus.FAIL, QCStatus.HOLD) and len(defects) == 0:
        errors.append("불합격/보류 상태에서는 불량 사유를 1개 이상 선택해야 합니다.")

    if errors:
        for e in errors:
            messages.error(request, e)
        return redirect("quality:incoming_inspect_layer", order_id=order.id)

    try:
        with transaction.atomic():
            header = IncomingInspection.objects.create(
                order=order,
                inspection_date=inspection_date,
                status=status,
                defects=defects,
                inspect_qty=inspect_qty,
                return_qty=return_qty,
                remark=remark,
                **({"shipment_id": shipment_id} if HAS_SHIPMENT_FIELD and shipment_id is not None else {}),
            )

            # 라인이 존재하는 경우에만 라인 스냅 생성(없으면 헤더만)
            if lines:
                IncomingInspectionDetail.objects.bulk_create([
                    IncomingInspectionDetail(
                        inspection=header,
                        shipment_line=l,
                        qty=l.qty,
                        status=status,
                        defects=defects,
                        return_qty=0,
                        remark="",
                    )
                    for l in lines
                ])

    except Exception:  # pragma: no cover - 운영 로깅
        logger.exception("[QC][SAVE] ERROR order_id=%s shipment_id=%s", order.id, shipment_id)
        messages.error(request, "수입검사 저장 중 오류가 발생했습니다.")
        return redirect("quality:incoming_inspect_layer", order_id=order.id)

    messages.success(request, "수입검사 저장 완료")
    return redirect("quality:incoming_inspect_layer", order_id=order.id)
