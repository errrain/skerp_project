# quality/outgoing/views.py
from datetime import timedelta
from datetime import date
import re

from django.db import IntegrityError

from django.shortcuts import render, get_object_or_404, redirect
from django.views.decorators.http import require_GET, require_http_methods
from django.utils.dateparse import parse_date
from django.urls import reverse

import json
from django.utils import timezone

from production.models import WorkOrder
from production.orders.views import _today_localdate, _day_range_for
from quality.inspections.models import (
    OutgoingInspection,
    OutgoingInspectionDefect,
    OutgoingDefectCode,
    OutgoingDefectGroup,
    OutgoingStatus,
    InspectionResult,
    OutgoingFinishedLot,
)

# 제품에 package_quantity 없을 때만 쓰는 기본값
DEFAULT_BOX_SIZE = 24

def _to_int(value, default=0):
    """빈값/콤마 포함 숫자 문자열을 안전하게 int로 변환."""
    if value is None:
        return default
    if isinstance(value, int):
        return value
    try:
        s = str(value).replace(",", "").strip()
        return int(s) if s else default
    except (ValueError, TypeError):
        return default


def _get_outgoing_list_context(request):
    """
    출하검사 리스트 공통 컨텍스트 (PC/현장 공용)
    """
    d_str = (request.GET.get("d") or "").strip()
    try:
        query_date = parse_date(d_str) if d_str else _today_localdate()
    except Exception:
        query_date = _today_localdate()

    start_dt, end_dt = _day_range_for(query_date)

    orders_qs = (
        WorkOrder.objects
        .filter(
            planned_start__gte=start_dt,
            planned_start__lt=end_dt,
            status="완료",  # 생산완료만 대상
        )
        .select_related("product", "customer", "outgoing_inspection")
        .order_by("planned_start", "created_at", "id")
    )

    return {
        "orders": orders_qs,
        "query_date": query_date,
        "prev_date": query_date - timedelta(days=1),
        "next_date": query_date + timedelta(days=1),
    }

def _next_finished_lot_code(inspect_date: date | None) -> str:
    """
    C-YYYYMMDD-XX 형식의 LOT 번호를 생성한다.
    - YYYYMMDD: 검사일(inspection_date) 기준, 없으면 오늘 날짜
    - XX     : 해당 날짜 기준 증가하는 2자리 시퀀스
    """
    if inspect_date is None:
        from django.utils import timezone
        inspect_date = timezone.localdate()

    base = inspect_date.strftime("%Y%m%d")
    prefix = f"C-{base}-"

    # 이미 존재하는 LOT 중에서 해당 날짜(prefix)로 시작하는 것들 중
    # 가장 마지막 코드 하나만 가져와서 seq 를 파싱
    last_code = (
        OutgoingFinishedLot.objects.filter(finished_lot__startswith=prefix)
        .order_by("-finished_lot")
        .values_list("finished_lot", flat=True)
        .first()
    )

    last_seq = 0
    if last_code:
        try:
            last_seq = int(last_code.split("-")[-1])
        except ValueError:
            last_seq = 0

    new_seq = last_seq + 1
    return f"{prefix}{new_seq:02d}"


@require_GET
def outgoing_list(request):
    """
    출하검사 목록 (관리자 화면)
    """
    ctx = _get_outgoing_list_context(request)
    return render(request, "quality/outgoing/outgoing_list.html", ctx)


@require_GET
def outgoing_site_list(request):
    """
    출하검사 목록 (현장용 – 태블릿/키오스크)
    """
    ctx = _get_outgoing_list_context(request)
    return render(request, "quality/outgoing/outgoing_site_list.html", ctx)


@require_http_methods(["GET", "POST"])
def outgoing_inspect(request, workorder_id: int, mode: str = "admin"):
    """
    출하검사 입력/확인 화면

    - mode = "admin" : PC 관리자용 (outgoing_form.html)
    - mode = "site"  : 현장용   (outgoing_site_form.html)

    URL 의 pk 는 항상 WorkOrder.pk 를 사용한다.
    OutgoingInspection 는 WorkOrder 당 1건을 원칙으로 하며,
    OutgoingFinishedLot 역시 해당 WorkOrder 의 검사 한 건에만 귀속된다.
    """

    # 1) 작업 LOT / 계획수량 / 박스당 포장수량
    workorder = get_object_or_404(
        WorkOrder.objects.select_related("product", "customer"),
        pk=workorder_id,
    )
    plan_qty = workorder.order_qty or 0

    product = workorder.product
    box_size = getattr(product, "package_quantity", None) or DEFAULT_BOX_SIZE

    # 2) 출하검사 헤더 조회 또는 생성 (WorkOrder 기준 1건)
    inspection, created = OutgoingInspection.objects.get_or_create(
        workorder=workorder,
        defaults={
            "inspection_date": _today_localdate(),
            "inspect_qty": 0,
            "good_qty": 0,
            "defect_qty": 0,
            "loss_qty": 0,
            "hold_qty": 0,
            "adjust_qty": 0,
            "status": OutgoingStatus.DRAFT,
            "result": InspectionResult.NONE,
        },
    )

    # ------------------------------------------------------------------ #
    # POST: 저장 / 삭제
    # ------------------------------------------------------------------ #
    if request.method == "POST":
        action = (request.POST.get("action") or "save").strip() or "save"

        # ---------------- 삭제 (검사 전체 삭제) ----------------
        if action == "delete":
            # 이 WorkOrder 에 연결된 검사 + BOX 전체 삭제
            OutgoingInspectionDefect.objects.filter(inspection=inspection).delete()
            OutgoingFinishedLot.objects.filter(
                inspection__workorder=workorder
            ).delete()
            inspection.delete()

            redirect_name = (
                "quality:outgoing_site_list"
                if mode == "site"
                else "quality:outgoing_list"
            )
            base_date = (workorder.planned_start or workorder.created_at).date()
            return redirect(f"{reverse(redirect_name)}?d={base_date:%Y-%m-%d}")

        # ---------------- 저장 ----------------

        # 1) 기본 정보
        inspection.inspection_date = (
            parse_date(request.POST.get("inspection_date") or "")
            or inspection.inspection_date
        )

        posted_status = (request.POST.get("status") or "").strip()
        if posted_status:
            inspection.status = posted_status

        posted_result = (request.POST.get("result") or "").strip()
        if posted_result:
            inspection.result = posted_result

        is_finalized = request.POST.get("finalized") == "1"

        # 실수량 보정(±EA) - POST 값이 없으면 기존 값 유지
        raw_adjust = request.POST.get("adjust_qty")
        if raw_adjust is None or raw_adjust == "":
            adjusted = inspection.adjust_qty or 0
        else:
            adjusted = _to_int(raw_adjust, default=inspection.adjust_qty or 0)
        inspection.adjust_qty = adjusted

        # 관리자 화면에서만 들어오는 항목 – 현장화면에서는 키 없음
        if "adjust_reason" in request.POST:
            inspection.adjust_reason = request.POST.get("adjust_reason") or ""

        # LOSS (hidden)
        loss_qty = _to_int(request.POST.get("loss_qty"), default=0)

        # 2) 불량 코드별 수량
        codes = request.POST.getlist("defect_code")
        qtys = request.POST.getlist("defect_qty")

        # (기존 구조 호환: 맨 앞에 합계 한 칸이 끼어 있는 경우 잘라내기)
        if len(qtys) == len(codes) + 1:
            qtys = qtys[1:]
        else:
            qtys = qtys[: len(codes)]

        defect_rows: list[OutgoingInspectionDefect] = []
        total_defect_qty = 0

        for code, qty_str in zip(codes, qtys):
            qty = _to_int(qty_str, default=0)
            if qty <= 0:
                continue
            total_defect_qty += qty
            defect_rows.append(
                OutgoingInspectionDefect(
                    inspection=inspection,
                    code=code,
                    qty=qty,
                )
            )

        # 3) BOX LOT payload(JSON) 파싱
        raw_finished = (request.POST.get("finished_lots_payload") or "").strip()
        finished_payload: list[dict] = []
        if raw_finished:
            try:
                data = json.loads(raw_finished)
                if isinstance(data, list):
                    finished_payload = data
            except json.JSONDecodeError:
                finished_payload = []

        # 4) 수량 계산 (서버에서 최종 검증)
        adjust = inspection.adjust_qty or 0
        plan = plan_qty or 0

        # 계획 + 보정
        actual_total = plan + adjust

        # 완료 BOX 양품수량 = finished_payload 의 qty 합
        completed_qty = sum(
            _to_int(item.get("qty"), default=0) for item in finished_payload
        )
        good_qty = max(completed_qty, 0)

        # 4-1) 실측 검사수 = 양품 + 불량 + LOSS
        raw_inspect_qty = good_qty + total_defect_qty + loss_qty

        # 4-2) 최종 인정 검사수량 = 실측 + 보정값
        inspect_qty = raw_inspect_qty + adjust

        # 4-3) 미검사 잔여수량 (BOX/마감 로직용)
        remain_qty = max(actual_total - raw_inspect_qty, 0)

        # 5) 검사 상태 보정 (서버 기준)
        if inspect_qty == 0:
            inspection.status = OutgoingStatus.WAIT
        elif remain_qty > 0:
            inspection.status = OutgoingStatus.HOLD   # 진행중(잔여 있음)
        else:
            inspection.status = OutgoingStatus.DONE   # 잔여 0 ⇒ 마감

        # 현장 화면에서 finalized=1 이면 DONE 강제
        if mode == "site" and is_finalized:
            inspection.status = OutgoingStatus.DONE

        # 6) 헤더 수량 반영
        inspection.inspect_qty = inspect_qty
        inspection.loss_qty = loss_qty
        inspection.defect_qty = total_defect_qty
        inspection.good_qty = good_qty
        inspection.hold_qty = 0      # HOLD 개념 폐지

        # 7) DB 저장
        #   7-1) 불량 상세
        OutgoingInspectionDefect.objects.filter(inspection=inspection).delete()
        if defect_rows:
            OutgoingInspectionDefect.objects.bulk_create(defect_rows)

        #   7-2) 헤더 저장
        inspection.save()

        #   7-3) BOX LOT 동기화 (SOFT DELETE + 임시포장 처리)
        #
        #   - 기존 LOT 중 dlt_yn='N' 인 것들을 먼저 읽어 온다.
        #   - 화면에서 넘어온 finished_payload 와 매칭:
        #       * lot 값이 "C-YYYYMMDD-XX" 형식이면 → 기존 LOT 로 판단, UPDATE
        #       * 그 외(임시포장 1, 임시포장 2 …)  → 신규 LOT 로 판단, CREATE
        #   - 기존 LOT 중 화면에 없는 것들은 dlt_yn='Y' 로 SOFT DELETE
        existing_qs = OutgoingFinishedLot.objects.filter(
            inspection=inspection,
            dlt_yn="N",
        )
        existing_map: dict[str, OutgoingFinishedLot] = {
            row.finished_lot: row for row in existing_qs
        }
        kept_codes: set[str] = set()

        lot_pattern = re.compile(r"^C-\d{8}-\d{2}$")
        inspect_date = inspection.inspection_date

        for item in finished_payload:
            qty = _to_int(item.get("qty"), default=0)
            if qty <= 0:
                continue

            status_code = (item.get("status") or "FULL").strip()
            if status_code not in ("FULL", "SHORT"):
                status_code = "FULL"

            raw_lot = (item.get("lot") or "").strip()
            is_existing = False

            # 7-3-1) 이미 발급된 LOT 인지 확인
            if raw_lot and lot_pattern.match(raw_lot):
                obj = existing_map.get(raw_lot)
                if obj is not None:
                    obj.box_size = qty
                    obj.status = status_code
                    obj.shipped = obj.shipped  # 기존 값 유지
                    obj.dlt_yn = "N"
                    obj.dlt_at = None
                    obj.dlt_user = None
                    obj.dlt_reason = ""
                    obj.save()
                    kept_codes.add(obj.finished_lot)
                    is_existing = True

            if is_existing:
                continue

            # 7-3-2) 신규 BOX → 서버에서 LOT 번호 발급
            while True:
                lot_no = _next_finished_lot_code(inspect_date)
                try:
                    new_obj = OutgoingFinishedLot.objects.create(
                        inspection=inspection,
                        finished_lot=lot_no,
                        box_size=qty,         # 실제 박스 수량
                        status=status_code,
                        shipped=False,
                        operator=(
                            request.user.username
                            if getattr(request, "user", None)
                            and request.user.is_authenticated
                            else None
                        ),
                        dlt_yn="N",
                    )
                    kept_codes.add(new_obj.finished_lot)
                    break
                except IntegrityError:
                    # 동시에 같은 LOT 번호를 발급받은 경우 → 다음 번호로 재시도
                    continue

        # 7-3-3) 기존 LOT 중 화면에 없는 것들 → SOFT DELETE
        removed_qs = existing_qs.exclude(finished_lot__in=kept_codes)
        if removed_qs.exists():
            now = timezone.now()
            dlt_user = (
                request.user.username
                if getattr(request, "user", None)
                and request.user.is_authenticated
                else None
            )
            removed_qs.update(
                dlt_yn="Y",
                dlt_at=now,
                dlt_user=dlt_user,
                dlt_reason="출하검사(현장) 화면에서 삭제",
            )

        # 8) 저장 후 자기 자신으로 리다이렉트
        redirect_name = (
            "quality:outgoing_site_inspect"
            if mode == "site"
            else "quality:outgoing_inspect"
        )
        return redirect(redirect_name, workorder_id=workorder.id)

    # ------------------------------------------------------------------ #
    # GET: 화면 표시
    # ------------------------------------------------------------------ #

    # 불량 코드 복원
    defect_qs = OutgoingInspectionDefect.objects.filter(inspection=inspection)
    defect_map = {row.code: row.qty for row in defect_qs}

    plating_codes: list[dict] = []
    injection_codes: list[dict] = []
    for code in OutgoingDefectCode:
        group = OutgoingDefectCode.group_of(code.value)
        item = {
            "code": code.value,
            "label": code.label,
            "qty": defect_map.get(code.value, 0),
        }
        if group == OutgoingDefectGroup.PLATING:
            plating_codes.append(item)
        else:
            injection_codes.append(item)

    # BOX LOT 복원 – dlt_yn='N' 인 것만 화면에 노출
    lot_qs = OutgoingFinishedLot.objects.filter(
        inspection=inspection,
        dlt_yn="N",
    ).order_by("id")

    finished_payload: list[dict] = []
    for idx, lot in enumerate(lot_qs, start=1):
        finished_payload.append(
            {
                "seq": idx,
                "lot": lot.finished_lot,   # 이미 발급된 LOT 번호
                "qty": lot.box_size,       # 실제 수량
                "box_size": box_size,      # 기준 박스 수량
                "status": lot.status,      # FULL / SHORT 코드
            }
        )
    finished_lots_json = json.dumps(finished_payload, ensure_ascii=False)

    # 디버그 로그(필요 시)
    import logging
    logger = logging.getLogger(__name__)
    logger.info("=== OUTGOING_SITE GET === workorder_id=%s", workorder.id)
    logger.info(
        "inspection_id=%s, status=%s, inspect_qty=%s, good_qty=%s, defect_qty=%s, loss_qty=%s, adjust_qty=%s",
        inspection.id if inspection else None,
        inspection.status if inspection else None,
        inspection.inspect_qty,
        inspection.good_qty,
        inspection.defect_qty,
        inspection.loss_qty,
        inspection.adjust_qty,
    )
    logger.info("finished_payload=%s", finished_payload)

    template_name = (
        "quality/outgoing/outgoing_site_form.html"
        if mode == "site"
        else "quality/outgoing/outgoing_form.html"
    )

    ctx = {
        "workorder": workorder,
        "inspection": inspection,
        "plating_codes": plating_codes,
        "injection_codes": injection_codes,
        "mode": mode,
        "finished_lots_json": finished_lots_json,
        "plan_qty": plan_qty,
        "box_size": box_size,
    }
    return render(request, template_name, ctx)
