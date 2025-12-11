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
    FinishedBox,        # ✅ 추가
    FinishedBoxFill,    # ✅ 추가
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

    # 상세 화면 카드와 동일한 값 계산을 위해
    # 각 WorkOrder 객체에 계산 결과를 얹어서 전달
    orders = list(orders_qs)

    for o in orders:
        # 계획검사수량(지시수량) = 작업수량
        plan_qty = o.order_qty or 0

        # 박스당 포장수량
        product = getattr(o, "product", None)
        box_size = getattr(product, "package_quantity", None) or DEFAULT_BOX_SIZE
        o.box_size_for_outgoing = box_size

        insp = getattr(o, "outgoing_inspection", None)

        remain_qty = None          # 미검사 잔여수량
        finished_box_cnt = None    # 포장완료 BOX 수
        # 포장완료수량은 insp.good_qty 그대로 사용

        if insp is not None:
            adjust = insp.adjust_qty or 0
            good = insp.good_qty or 0
            defect = insp.defect_qty or 0
            loss = insp.loss_qty or 0

            # 상세화면 로직과 동일:
            # actual_total = PLAN + adjust
            # raw_inspect = good + defect + loss
            # remain = max(actual_total - raw_inspect, 0)
            actual_total = plan_qty + adjust
            raw_inspect = good + defect + loss
            remain_qty = max(actual_total - raw_inspect, 0)

            # 포장완료 BOX 수 = good / BOX_SIZE
            if box_size > 0:
                finished_box_cnt = good // box_size
            else:
                finished_box_cnt = 0

        o.remain_qty_for_outgoing = remain_qty
        o.finished_box_cnt_for_outgoing = finished_box_cnt

    return {
        "orders": orders,
        "query_date": query_date,
        "prev_date": query_date - timedelta(days=1),
        "next_date": query_date + timedelta(days=1),
    }

def _next_finished_lot_code(inspect_date: date | None) -> str:
    """
    C-YYYYMMDD-XX 형식의 LOT 번호를 생성한다.
    - YYYYMMDD: 검사일(inspection_date) 기준, 없으면 오늘 날짜
    - XX     : 해당 날짜 기준 증가하는 2자리 시퀀스

    ⚠ 단계적 이관을 위해
    - 새 마스터 테이블 FinishedBox.lot_no
    - 기존 OutgoingFinishedLot.finished_lot
    둘을 모두 조회해서 가장 큰 시퀀스를 기준으로 다음 번호를 만든다.
    """

    if inspect_date is None:
        inspect_date = timezone.localdate()

    base = inspect_date.strftime("%Y%m%d")
    prefix = f"C-{base}-"

    # 1) 새 구조: FinishedBox 기준으로 가장 마지막 LOT 가져오기
    last_box_code = (
        FinishedBox.objects.filter(
            lot_no__startswith=prefix,
            dlt_yn="N",
        )
        .order_by("-lot_no")
        .values_list("lot_no", flat=True)
        .first()
    )

    # 2) 기존 구조: OutgoingFinishedLot 기준(과거/기존 데이터용)
    last_old_code = (
        OutgoingFinishedLot.objects.filter(
            finished_lot__startswith=prefix,
            dlt_yn="N",
        )
        .order_by("-finished_lot")
        .values_list("finished_lot", flat=True)
        .first()
    )

    # 3) 두 쪽에서 가져온 코드들 중 가장 큰 시퀀스를 찾는다.
    candidates: list[str] = []
    if last_box_code:
        candidates.append(last_box_code)
    if last_old_code:
        candidates.append(last_old_code)

    last_seq = 0
    for code in candidates:
        try:
            seq = int(code.split("-")[-1])
        except (ValueError, AttributeError):
            continue
        if seq > last_seq:
            last_seq = seq

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

        # ✅ 완료 BOX 양품수량 계산
        # - 일반 BOX   : qty 전체를 이번 작업 good 으로 본다
        # - 잔량 BOX   : add_qty(이번 작업에서 채운 수량)만 good 으로 본다
        completed_qty = 0
        for item in finished_payload:
            is_residual = bool(item.get("isResidual"))
            qty       = _to_int(item.get("qty"), default=0)
            base_qty  = _to_int(item.get("base_qty"), default=0)
            add_qty   = _to_int(item.get("add_qty"), default=0)

            if is_residual:
                # 잔량 BOX: 이번 작업에서 채운 수량만 검사수량으로 인정
                completed_qty += max(add_qty, 0)
            else:
                # 일반 BOX: 화면의 qty 전체를 이번 작업 검사 양품으로 인정
                completed_qty += max(qty, 0)

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

        #   7-3) BOX LOT 동기화
        #   - OutgoingFinishedLot : 기존처럼 유지
        #   - FinishedBox         : LOT(BOX) 마스터 1:1 생성/갱신
        #   - FinishedBoxFill     : 이 출하검사에서 해당 BOX 에 채운 수량 기록

        #   7-3-0) 기존 BOX/LOT 조회
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

            raw_lot    = (item.get("lot") or "").strip()
            is_residual = bool(item.get("isResidual"))
            base_qty   = _to_int(item.get("base_qty"), default=0)
            add_qty    = _to_int(item.get("add_qty"), default=0)

            # -------------------------------------------------------
            # 7-3-1) 잔량 BOX(C-LOT) 처리
            #   - FinishedBox(lot_no=raw_lot) UPDATE
            #   - FinishedBoxFill(이번 작업에서 채운 수량) INSERT
            #   - OutgoingFinishedLot(이번 검사와 LOT 연결) UPSERT
            # -------------------------------------------------------
            if is_residual and raw_lot and lot_pattern.match(raw_lot):
                final_qty = max(base_qty + add_qty, 0)

                # BoxMaster(FinishedBox) 갱신
                try:
                    box = FinishedBox.objects.get(lot_no=raw_lot, dlt_yn="N")
                except FinishedBox.DoesNotExist:
                    box = None

                if box is not None:
                    box.qty = final_qty
                    box.status = status_code
                    # product / box_size / shipped 는 그대로 유지
                    box.save()

                    # 이번 작업에서 채운 수량이 있다면 Fill 이력 추가
                    if add_qty > 0:
                        FinishedBoxFill.objects.create(
                            box=box,
                            inspection=inspection,
                            qty_added=add_qty,
                            filled_at=timezone.now(),
                        )

                # 이 검사와 LOT 연결(OutgoingFinishedLot)
                obj = existing_map.get(raw_lot)
                if obj is not None:
                    obj.box_size = final_qty
                    obj.status = status_code
                    obj.shipped = obj.shipped
                    obj.dlt_yn = "N"
                    obj.dlt_at = None
                    obj.dlt_user = None
                    obj.dlt_reason = ""
                    obj.save()
                else:
                    obj = OutgoingFinishedLot.objects.create(
                        inspection=inspection,
                        finished_lot=raw_lot,
                        box_size=final_qty,
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

                kept_codes.add(obj.finished_lot)
                continue  # 잔량 BOX 처리 끝

            # -------------------------------------------------------
            # 7-3-2) 일반 BOX 처리 (임시포장 + 기존 C-코드)
            #   - C-코드이고 이 검사에 이미 존재 → OutgoingFinishedLot/FinishedBox UPDATE
            #   - 그 외(임시포장) → 새 LOT 발급 + FinishedBox/FinishedBoxFill CREATE
            # -------------------------------------------------------
            obj = None

            if raw_lot and lot_pattern.match(raw_lot):
                # 이 검사에서 이미 존재하던 LOT → UPDATE
                obj = existing_map.get(raw_lot)
                if obj is not None:
                    obj.box_size = qty
                    obj.status = status_code
                    obj.shipped = obj.shipped
                    obj.dlt_yn = "N"
                    obj.dlt_at = None
                    obj.dlt_user = None
                    obj.dlt_reason = ""
                    obj.save()

                    # BoxMaster 도 있으면 qty/status 동기화
                    try:
                        box = FinishedBox.objects.get(lot_no=raw_lot, dlt_yn="N")
                    except FinishedBox.DoesNotExist:
                        box = None
                    if box is not None:
                        box.qty = qty
                        box.status = status_code
                        box.save()

                    kept_codes.add(obj.finished_lot)
                    continue  # 기존 LOT 업데이트만 하고 다음 item 으로

            # 여기까지 왔으면 "새 BOX" 이므로 LOT 코드를 발급
            while True:
                lot_no = _next_finished_lot_code(inspect_date)
                try:
                    obj = OutgoingFinishedLot.objects.create(
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

                    # BoxMaster(FinishedBox) 생성
                    box = FinishedBox.objects.create(
                        lot_no=lot_no,
                        product=product,
                        box_size=box_size,   # 기준 BOX 수량
                        qty=qty,             # 현재 담긴 수량
                        status=status_code,
                        shipped=False,
                        dlt_yn="N",
                    )
                    # 이번 작업에서 전량을 채운 이력
                    FinishedBoxFill.objects.create(
                        box=box,
                        inspection=inspection,
                        qty_added=qty,
                        filled_at=timezone.now(),
                    )

                    kept_codes.add(obj.finished_lot)
                    break
                except IntegrityError:
                    # 동시에 같은 LOT 번호를 발급받은 경우 → 다음 번호로 재시도
                    continue

        # 7-3-3) 기존 LOT 중 화면에 없는 것들 → SOFT DELETE
        removed_qs = existing_qs.exclude(finished_lot__in=kept_codes)
        if removed_qs.exists():
            now = timezone.now()
            dlt_user = operator_name

            removed_lots = list(
                removed_qs.values_list("finished_lot", flat=True)
            )

            removed_qs.update(
                dlt_yn="Y",
                dlt_at=now,
                dlt_user=dlt_user,
                dlt_reason="출하검사(현장) 화면에서 삭제",
            )

            # BOX 마스터도 함께 비활성화 (현재는 1:1 매핑이므로 그대로 Y 처리)
            FinishedBox.objects.filter(lot_no__in=removed_lots).update(
                dlt_yn="Y",
                dlt_at=now,
                dlt_user=dlt_user,
                dlt_reason="출하검사(현장) BOX 삭제 연동",
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

    # ✅ 동일 품목의 잔량 BOX(= SHORT, 미출하, 삭제 안됨) 목록
    residual_boxes_qs = FinishedBox.objects.filter(
        product=workorder.product,
        status="SHORT",
        shipped=False,
        dlt_yn="N",
    ).order_by("lot_no")

    residual_boxes_payload: list[dict] = []
    for box in residual_boxes_qs:
        residual_boxes_payload.append(
            {
                "lot": box.lot_no,
                "qty": box.qty,
                "box_size": box.box_size,
                "status": box.status,
            }
        )
    residual_boxes_json = json.dumps(residual_boxes_payload, ensure_ascii=False)

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
        "residual_boxes_json": residual_boxes_json,  # ✅ 추가
    }
    return render(request, template_name, ctx)

