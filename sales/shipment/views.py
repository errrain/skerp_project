#/sales/shipment/views.py
import json
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_GET
from django.db import transaction, models
from django.apps import apps
from django.shortcuts import render
from django.db.models import Q

from ..models import SalesShipment, SalesShipmentLine


def shipment_list(request):
    """
    출하 목록 (헤더 리스트)
    검색조건:
      - sh_lot: 출하 LOT (부분일치)
      - ship_date_from, ship_date_to: 출하일 기간
      - customer: 고객사명 (부분일치)
      - program: 프로그램명
      - product_name: 품명
    """
    sh_lot = (request.GET.get("sh_lot") or "").strip()
    ship_date_from = (request.GET.get("ship_date_from") or "").strip()
    ship_date_to = (request.GET.get("ship_date_to") or "").strip()
    customer = (request.GET.get("customer") or "").strip()
    program = (request.GET.get("program") or "").strip()
    product_name = (request.GET.get("product_name") or "").strip()

    qs = (
        SalesShipment.objects
        .select_related("customer")
        .filter(delete_yn="N")  # 삭제 플래그가 있다면
        .order_by("-ship_date", "-id")
    )

    if sh_lot:
        qs = qs.filter(sh_lot__icontains=sh_lot)
    if customer:
        qs = qs.filter(customer__name__icontains=customer)
    if program:
        qs = qs.filter(program__icontains=program)
    if product_name:
        qs = qs.filter(product_name__icontains=product_name)

    if ship_date_from:
        dt_from = parse_date(ship_date_from)
        if dt_from:
            qs = qs.filter(ship_date__gte=dt_from)
    if ship_date_to:
        dt_to = parse_date(ship_date_to)
        if dt_to:
            qs = qs.filter(ship_date__lte=dt_to)

    shipments = qs

    context = {
        "shipments": shipments,
        "sh_lot": sh_lot,
        "ship_date_from": ship_date_from,
        "ship_date_to": ship_date_to,
        "customer": customer,
        "program": program,
        "product_name": product_name,
    }
    return render(request, "shipment/shipment_list.html", context)

def generate_sh_lot(ship_date):
    prefix = ship_date.strftime("SH%Y%m%d")
    last = (
        SalesShipment.objects
        .filter(sh_lot__startswith=prefix)
        .order_by("-sh_lot")
        .first()
    )
    if last:
        try:
            seq = int(last.sh_lot[-3:]) + 1
        except ValueError:
            seq = 1
    else:
        seq = 1
    return f"{prefix}-{seq:03d}"



def shipment_create(request):
    """
    출하 등록 - 1단계
    - 프로그램/품명으로 C-LOT 검색
    - 각 C-LOT에 대해 발주LOT / 입고LOT(사출일) / 생산LOT / 검사LOT / 검사자까지 세팅
    """
    FinishedBox = apps.get_model("quality", "FinishedBox")
    OutgoingFinishedLot = apps.get_model("quality", "OutgoingFinishedLot")  # ✅ 검사자 출처
    OutgoingInspection = apps.get_model("quality", "OutgoingInspection")
    WorkOrder = apps.get_model("production", "WorkOrder")
    WorkOrderInjectionUsage = apps.get_model("production", "WorkOrderInjectionUsage")
    InjectionReceiptLine = apps.get_model("purchase", "InjectionReceiptLine")
    InjectionReceipt = apps.get_model("purchase", "InjectionReceipt")
    InjectionOrder = apps.get_model("injectionorder", "InjectionOrder")

    program = request.GET.get("program", "").strip()
    product_name = request.GET.get("product_name", "").strip()

    box_qs = FinishedBox.objects.none()

    # 🔹 검색 조건이 있을 때만 C-LOT 조회
    if program or product_name:
        box_qs = (
            FinishedBox.objects.filter(
                shipped=False,   # 아직 출하 안 된 것만
                dlt_yn="N",
            )
            .select_related("product")
            .order_by("lot_no")
        )

        if program:
            box_qs = box_qs.filter(product__program_name__icontains=program)

        if product_name:
            box_qs = box_qs.filter(product__name__icontains=product_name)

    box_list = list(box_qs)

    if box_list:
        # ---------------------------------------------------------------
        # 1) C-LOT → 출하검사 / 검사자 매핑 (OutgoingFinishedLot 기준)
        # ---------------------------------------------------------------
        lot_nos = [b.lot_no for b in box_list]

        ofl_qs = (
            OutgoingFinishedLot.objects.filter(
                finished_lot__in=lot_nos,
                dlt_yn="N",
            )
            .select_related("inspection")
            .order_by("finished_lot", "-id")  # 같은 LOT 여러 건이면 최신 id 우선
        )

        inspection_by_lot = {}
        inspector_by_lot = {}
        for row in ofl_qs:
            code = row.finished_lot
            if code not in inspection_by_lot:
                inspection_by_lot[code] = row.inspection
                inspector_by_lot[code] = row.operator or ""

        # ---------------------------------------------------------------
        # 2) inspection → workorder 매핑
        # ---------------------------------------------------------------
        inspections = [ins for ins in inspection_by_lot.values() if ins is not None]
        workorder_ids = {
            ins.workorder_id
            for ins in inspections
            if getattr(ins, "workorder_id", None)
        }
        workorders = WorkOrder.objects.filter(id__in=workorder_ids)
        workorder_by_id = {w.id: w for w in workorders}

        # ---------------------------------------------------------------
        # 3) workorder → 사출 투입라인 / 입고 / 발주 LOT 역추적
        # ---------------------------------------------------------------
        usages = WorkOrderInjectionUsage.objects.filter(workorder_id__in=workorder_ids)
        line_ids = {u.line_id for u in usages}
        usage_by_workorder = {}
        for u in usages:
            if u.workorder_id not in usage_by_workorder:
                usage_by_workorder[u.workorder_id] = u

        lines = InjectionReceiptLine.objects.filter(id__in=line_ids)
        receipt_ids = {ln.receipt_id for ln in lines}
        line_by_id = {ln.id: ln for ln in lines}

        receipts = InjectionReceipt.objects.filter(id__in=receipt_ids)
        receipt_by_id = {r.id: r for r in receipts}

        order_ids = {
            r.order_id for r in receipts if getattr(r, "order_id", None)
        }
        orders = InjectionOrder.objects.filter(id__in=order_ids)
        order_by_id = {o.id: o for o in orders}

        # ---------------------------------------------------------------
        # 4) 화면 표시용 필드 세팅
        # ---------------------------------------------------------------
        for b in box_list:
            # C-LOT 기준으로 출하검사 헤더/작업지시 찾아오기
            ins = inspection_by_lot.get(b.lot_no)
            wo = workorder_by_id.get(ins.workorder_id) if ins else None
            usage = usage_by_workorder.get(wo.id) if wo else None
            line = line_by_id.get(usage.line_id) if usage else None
            receipt = receipt_by_id.get(line.receipt_id) if line else None
            order = order_by_id.get(receipt.order_id) if receipt else None

            # 수량
            b.qty_for_outgoing = getattr(b, "qty", 0)
            b.display_qty = b.qty_for_outgoing  # ✅ 템플릿 호환용
            # 발주 LOT
            b.order_lot = getattr(order, "order_lot", "") if order else ""

            # 입고 LOT (사출일)
            if receipt and line:
                # 1) LOT 문자열: 서브 LOT 우선
                lot_str = getattr(line, "sub_lot", None) or getattr(
                    receipt, "receipt_lot", ""
                )

                # 2) 협력사 생산일: PartnerShipmentLine.production_date 를 타고 올라감
                detail = getattr(line, "detail", None)  # IncomingInspectionDetail
                ship_line = getattr(detail, "shipment_line", None)  # PartnerShipmentLine

                inj_date = getattr(ship_line, "production_date", None)

                # 없으면 마지막 fallback 으로 입고일
                if not inj_date:
                    inj_date = getattr(receipt, "date", None)

                date_str = inj_date.strftime("%Y-%m-%d") if inj_date else ""

                b.in_lot = f"{lot_str} ({date_str})"
            else:
                b.in_lot = ""

            # 생산 LOT
            b.work_lot = getattr(wo, "work_lot", "") if wo else ""

            # 검사 LOT = C-LOT
            b.inspect_lot = getattr(b, "lot_no", "")

            # ✅ 검사자 (출하검사자)
            b.inspector = inspector_by_lot.get(b.lot_no, "")

            # 프로그램 / 품명
            b.program = getattr(b.product, "program_name", "")
            b.product_name = getattr(b.product, "name", "")

            # ✅ 고객사 이름 (product.customer.name 기준)
            customer = getattr(b.product, "customer", None)
            b.customer_name = getattr(customer, "name", "") if customer else ""

    current_user_name = (
            getattr(request.user, "full_name", None)
            or getattr(request.user, "username", "")
    )

    context = {
        "program": program,
        "product_name": product_name,
        "box_list": box_list,
        "current_user_name": current_user_name,  # ✅ 추가
    }
    return render(request, "shipment/shipment_form.html", context)



def shipment_detail(request, pk):
    """
    출하 상세 화면
    - 출하 마스터 + 라인별 LOT 추적 정보 표시
    """
    shipment = get_object_or_404(SalesShipment, pk=pk)

    # 출하 라인 가져오기
    lines = list(
        SalesShipmentLine.objects
        .select_related("product", "finished_box")
        .filter(shipment=shipment, delete_yn="N")
        .order_by("id")
    )

    # 라인이 있을 때만 LOT 역추적 수행
    if lines:
        FinishedBox = apps.get_model("quality", "FinishedBox")
        OutgoingFinishedLot = apps.get_model("quality", "OutgoingFinishedLot")
        OutgoingInspection = apps.get_model("quality", "OutgoingInspection")
        WorkOrder = apps.get_model("production", "WorkOrder")
        WorkOrderInjectionUsage = apps.get_model("production", "WorkOrderInjectionUsage")
        InjectionReceiptLine = apps.get_model("purchase", "InjectionReceiptLine")
        InjectionReceipt = apps.get_model("purchase", "InjectionReceipt")
        InjectionOrder = apps.get_model("injectionorder", "InjectionOrder")

        # 이번 출하에 포함된 BOX 목록
        box_list = [ln.finished_box for ln in lines if ln.finished_box_id]

        if box_list:
            # 1) C-LOT → 출하검사/검사자 매핑
            lot_nos = [b.lot_no for b in box_list]

            ofl_qs = (
                OutgoingFinishedLot.objects.filter(
                    finished_lot__in=lot_nos,
                    dlt_yn="N",
                )
                .select_related("inspection")
                .order_by("finished_lot", "-id")
            )

            inspection_by_lot: dict[str, OutgoingInspection] = {}
            inspector_by_lot: dict[str, str] = {}

            for row in ofl_qs:
                code = row.finished_lot
                if code not in inspection_by_lot:
                    inspection_by_lot[code] = row.inspection
                    inspector_by_lot[code] = row.operator or ""

            # 2) inspection → workorder 매핑
            inspections = [ins for ins in inspection_by_lot.values() if ins is not None]
            workorder_ids = {
                ins.workorder_id
                for ins in inspections
                if getattr(ins, "workorder_id", None)
            }
            workorders = WorkOrder.objects.filter(id__in=workorder_ids)
            workorder_by_id = {w.id: w for w in workorders}

            # 3) workorder → 사출 투입라인 / 입고 / 발주 LOT 역추적
            usages = WorkOrderInjectionUsage.objects.filter(workorder_id__in=workorder_ids)
            line_ids = {u.line_id for u in usages}
            usage_by_workorder = {}
            for u in usages:
                if u.workorder_id not in usage_by_workorder:
                    usage_by_workorder[u.workorder_id] = u

            rec_lines = InjectionReceiptLine.objects.filter(id__in=line_ids)
            receipt_ids = {ln.receipt_id for ln in rec_lines}
            line_by_id = {ln.id: ln for ln in rec_lines}

            receipts = InjectionReceipt.objects.filter(id__in=receipt_ids)
            receipt_by_id = {r.id: r for r in receipts}

            order_ids = {
                r.order_id for r in receipts if getattr(r, "order_id", None)
            }
            orders = InjectionOrder.objects.filter(id__in=order_ids)
            order_by_id = {o.id: o for o in orders}

            # 4) FinishedBox 객체에 표시용 필드 세팅
            for b in box_list:
                ins = inspection_by_lot.get(b.lot_no)
                wo = workorder_by_id.get(ins.workorder_id) if ins else None
                usage = usage_by_workorder.get(wo.id) if wo else None
                rec_line = line_by_id.get(usage.line_id) if usage else None
                receipt = receipt_by_id.get(rec_line.receipt_id) if rec_line else None
                order = order_by_id.get(receipt.order_id) if receipt else None

                # 발주 LOT
                b.order_lot = getattr(order, "order_lot", "") if order else ""

                # 입고 LOT (사출일)
                if receipt and rec_line:
                    lot_str = getattr(rec_line, "sub_lot", None) or getattr(
                        receipt, "receipt_lot", ""
                    )

                    detail = getattr(rec_line, "detail", None)
                    ship_line = getattr(detail, "shipment_line", None)

                    inj_date = getattr(ship_line, "production_date", None)
                    if not inj_date:
                        inj_date = getattr(receipt, "date", None)

                    date_str = inj_date.strftime("%Y-%m-%d") if inj_date else ""
                    b.in_lot = f"{lot_str} ({date_str})"
                else:
                    b.in_lot = ""

                # 생산 LOT
                b.work_lot = getattr(wo, "work_lot", "") if wo else ""

                # 검사 LOT = C-LOT
                b.inspect_lot = getattr(b, "lot_no", "")

                # 검사자
                b.inspector = inspector_by_lot.get(b.lot_no, "")

                # 프로그램 / 품명 (안전하게 캐싱)
                b.program = getattr(b.product, "program_name", "")
                b.product_name = getattr(b.product, "name", "")

    context = {
        "shipment": shipment,
        "lines": lines,
    }
    return render(request, "shipment/shipment_detail.html", context)


def order_match(request, shipment_id):
    """
    수주매칭 팝업 (임시)
    """
    return render(request, "shipment/order_match.html", {})

@require_POST
def shipment_save(request):
    import json

    data = json.loads(request.body.decode("utf-8"))
    box_ids = data.get("box_ids") or []
    ship_date_str = data.get("ship_date") or ""
    memo = data.get("memo") or ""
    operator = data.get("operator") or ""

    FinishedBox = apps.get_model("quality", "FinishedBox")
    OutgoingFinishedLot = apps.get_model("quality", "OutgoingFinishedLot")

    # 출하일 파싱
    ship_date = (
        timezone.datetime.fromisoformat(ship_date_str).date()
        if ship_date_str else timezone.localdate()
    )

    with transaction.atomic():
        boxes = (
            FinishedBox.objects
            .select_related("product")
            .filter(id__in=box_ids, dlt_yn="N", shipped=False)
        )
        box_list = list(boxes)
        if not box_list:
            return JsonResponse({"success": False, "message": "유효한 LOT 없습니다."}, status=400)

        product = box_list[0].product
        customer = getattr(product, "customer", None)

        sh_lot = generate_sh_lot(ship_date)
        user_name = (
            getattr(request.user, "full_name", None)
            or getattr(request.user, "username", "")
            or operator
        )

        total_qty = sum(getattr(b, "qty", 0) for b in box_list)

        # 🔹 출하 마스터 저장 (프로그램/품명/총수량/고객사 포함)
        shipment = SalesShipment.objects.create(
            sh_lot=sh_lot,
            customer=customer,
            ship_date=ship_date,
            program=getattr(product, "program_name", ""),
            product_name=getattr(product, "name", ""),
            total_qty=total_qty,
            operator=user_name,
            memo=memo,
            status="CONFIRMED",
            created_by=user_name,
            updated_by=user_name,
        )

        # 🔹 라인 + 상태 변경
        for b in box_list:
            qty = getattr(b, "qty", 0)

            SalesShipmentLine.objects.create(
                shipment=shipment,
                finished_box=b,
                product=b.product,
                c_lot=b.lot_no,
                quantity=qty,
                unit_price=0,
                total_price=0,
                created_by=user_name,
                updated_by=user_name,
            )

            # 1) BOX 마스터 상태: 출하완료
            b.shipped = True
            b.save(update_fields=["shipped"])

            # 2) 출하검사 LOT 상태: 출하완료
            OutgoingFinishedLot.objects.filter(
                finished_lot=b.lot_no,
                dlt_yn="N",
            ).update(shipped=True)

    return JsonResponse(
        {
            "success": True,
            "shipment_id": shipment.id,
            "sh_lot": sh_lot,
            "total_qty": total_qty,
        }
    )

@require_POST
def shipment_update(request, pk):
    """
    출하 수정:
    - delete_line_ids: 삭제할 출하 라인 id 리스트
    - add_clots: 새로 추가할 C-LOT 번호 리스트
    """
    try:
        data = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "message": "잘못된 요청입니다."}, status=400)

    delete_line_ids = data.get("delete_line_ids") or []
    add_clots = data.get("add_clots") or []

    shipment = get_object_or_404(SalesShipment, pk=pk)

    FinishedBox = apps.get_model("quality", "FinishedBox")
    OutgoingFinishedLot = apps.get_model("quality", "OutgoingFinishedLot")

    with transaction.atomic():
        # 🔹 1) 라인 삭제 처리
        if delete_line_ids:
            lines = list(
                SalesShipmentLine.objects
                .select_related("finished_box")
                .filter(id__in=delete_line_ids, shipment=shipment, delete_yn="N")
            )
            for ln in lines:
                fb = ln.finished_box
                # 출하 라인 soft delete
                ln.delete_yn = "Y"
                ln.save(update_fields=["delete_yn"])

                if fb:
                    # BOX 출하 취소
                    fb.shipped = False
                    fb.save(update_fields=["shipped"])
                    # 출하검사 LOT 출하 취소
                    OutgoingFinishedLot.objects.filter(
                        finished_lot=fb.lot_no,
                        dlt_yn="N",
                    ).update(shipped=False)

        # 🔹 2) C-LOT 추가 처리
        if add_clots:
            # LOT 번호 → FinishedBox 가져오기 (검사 완료 & 아직 출하 안 된 것만)
            boxes = list(
                FinishedBox.objects
                .select_related("product")
                .filter(
                    lot_no__in=add_clots,
                    dlt_yn="N",
                    shipped=False,
                )
            )
            if len(boxes) != len(add_clots):
                return JsonResponse(
                    {"success": False, "message": "유효하지 않은 C-LOT 이 포함되어 있습니다."},
                    status=400,
                )

            for b in boxes:
                qty = getattr(b, "qty", 0)
                SalesShipmentLine.objects.create(
                    shipment=shipment,
                    finished_box=b,
                    product=b.product,
                    c_lot=b.lot_no,
                    quantity=qty,
                    unit_price=0,
                    total_price=0,
                    created_by=request.user.username,
                    updated_by=request.user.username,
                )
                # BOX 출하 처리
                b.shipped = True
                b.save(update_fields=["shipped"])
                # 출하검사 LOT 출하 처리
                OutgoingFinishedLot.objects.filter(
                    finished_lot=b.lot_no,
                    dlt_yn="N",
                ).update(shipped=True)

        # 🔹 3) 총 출하수량 재계산
        total_qty = (
            SalesShipmentLine.objects
            .filter(shipment=shipment, delete_yn="N")
            .aggregate(sum_qty=models.Sum("quantity"))["sum_qty"] or 0
        )
        shipment.total_qty = total_qty
        shipment.save(update_fields=["total_qty"])

    return JsonResponse({"success": True})

@require_GET
def shipment_box_search(request, pk):
    """
    출하 상세에서 C-LOT 추가 검색용 API

    - 기준: 아직 출하되지 않은 FinishedBox (shipped=False, dlt_yn='N')
    - 현재 출하서에 이미 포함된 C-LOT 은 제외
    - 같은 고객사(product.customer == shipment.customer)만 조회
    - shipment_create 와 동일한 LOT 역추적 로직으로
      order_lot / in_lot / work_lot / inspect_lot / inspector 세팅
    """
    # 품목/로트 검색어
    program = (request.GET.get("program") or "").strip()
    product_name = (request.GET.get("product") or "").strip()
    c_lot = (request.GET.get("clot") or "").strip()

    FinishedBox = apps.get_model("quality", "FinishedBox")
    OutgoingFinishedLot = apps.get_model("quality", "OutgoingFinishedLot")
    WorkOrder = apps.get_model("production", "WorkOrder")
    WorkOrderInjectionUsage = apps.get_model("production", "WorkOrderInjectionUsage")
    InjectionReceiptLine = apps.get_model("purchase", "InjectionReceiptLine")
    InjectionReceipt = apps.get_model("purchase", "InjectionReceipt")
    InjectionOrder = apps.get_model("injectionorder", "InjectionOrder")

    # 기준 출하서
    shipment = get_object_or_404(
        SalesShipment.objects.select_related("customer"), pk=pk
    )

    # 이미 이 출하서에 들어간 C-LOT 은 검색 결과에서 제외
    used_lots = list(
        SalesShipmentLine.objects.filter(
            shipment=shipment,
            delete_yn="N",
        ).values_list("c_lot", flat=True)
    )

    # 기본 C-LOT 후보
    box_qs = (
        FinishedBox.objects.filter(
            shipped=False,
            dlt_yn="N",
        )
        .select_related("product")
        .order_by("lot_no")
    )

    # 같은 고객사 기준(제품에 customer 필드가 있다고 가정)
    if shipment.customer_id:
        box_qs = box_qs.filter(product__customer_id=shipment.customer_id)

    # 검색 조건
    if program:
        box_qs = box_qs.filter(product__program_name__icontains=program)
    if product_name:
        box_qs = box_qs.filter(product__name__icontains=product_name)
    if c_lot:
        box_qs = box_qs.filter(lot_no__icontains=c_lot)

    # 이미 사용된 C-LOT 제외
    if used_lots:
        box_qs = box_qs.exclude(lot_no__in=used_lots)

    box_list = list(box_qs)
    if not box_list:
        return JsonResponse({"success": True, "results": []})

    # ====== shipment_create 와 동일한 LOT 역추적 ======
    lot_nos = [b.lot_no for b in box_list]

    ofl_qs = (
        OutgoingFinishedLot.objects.filter(
            finished_lot__in=lot_nos,
            dlt_yn="N",
        )
        .select_related("inspection")
        .order_by("finished_lot", "-id")
    )

    inspection_by_lot = {}
    inspector_by_lot = {}
    for row in ofl_qs:
        code = row.finished_lot
        if code not in inspection_by_lot:
            inspection_by_lot[code] = row.inspection
            inspector_by_lot[code] = row.operator or ""

    inspections = [ins for ins in inspection_by_lot.values() if ins is not None]
    workorder_ids = {
        ins.workorder_id for ins in inspections if getattr(ins, "workorder_id", None)
    }
    workorders = WorkOrder.objects.filter(id__in=workorder_ids)
    workorder_by_id = {w.id: w for w in workorders}

    usages = WorkOrderInjectionUsage.objects.filter(workorder_id__in=workorder_ids)
    line_ids = {u.line_id for u in usages}
    usage_by_workorder = {}
    for u in usages:
        if u.workorder_id not in usage_by_workorder:
            usage_by_workorder[u.workorder_id] = u

    lines = InjectionReceiptLine.objects.filter(id__in=line_ids)
    receipt_ids = {ln.receipt_id for ln in lines}
    line_by_id = {ln.id: ln for ln in lines}

    receipts = InjectionReceipt.objects.filter(id__in=receipt_ids)
    receipt_by_id = {r.id: r for r in receipts}

    order_ids = {r.order_id for r in receipts if getattr(r, "order_id", None)}
    orders = InjectionOrder.objects.filter(id__in=order_ids)
    order_by_id = {o.id: o for o in orders}

    # box 에 표시값 채우기
    for b in box_list:
        ins = inspection_by_lot.get(b.lot_no)
        wo = workorder_by_id.get(ins.workorder_id) if ins else None
        usage = usage_by_workorder.get(wo.id) if wo else None
        line = line_by_id.get(usage.line_id) if usage else None
        receipt = receipt_by_id.get(line.receipt_id) if line else None
        order = order_by_id.get(receipt.order_id) if receipt else None

        b.qty_for_outgoing = getattr(b, "qty", 0)
        b.order_lot = getattr(order, "order_lot", "") if order else ""

        if receipt and line:
            lot_str = getattr(line, "sub_lot", None) or getattr(
                receipt, "receipt_lot", ""
            )
            detail = getattr(line, "detail", None)
            ship_line = getattr(detail, "shipment_line", None)
            inj_date = getattr(ship_line, "production_date", None)
            if not inj_date:
                inj_date = getattr(receipt, "date", None)
            date_str = inj_date.strftime("%Y-%m-%d") if inj_date else ""
            b.in_lot = f"{lot_str} ({date_str})"
        else:
            b.in_lot = ""

        b.work_lot = getattr(wo, "work_lot", "") if wo else ""
        b.inspect_lot = getattr(b, "lot_no", "")
        b.inspector = inspector_by_lot.get(b.lot_no, "")
        b.program = getattr(b.product, "program_name", "")
        b.product_name = getattr(b.product, "name", "")

    # JSON 응답용으로 직렬화
    results = [
        {
            "id": b.id,
            "program": b.program,
            "product_name": b.product_name,
            "qty": b.qty_for_outgoing,
            "order_lot": b.order_lot,
            "in_lot": b.in_lot,
            "work_lot": b.work_lot,
            # 🔹 C-LOT (검사 LOT) – JS 에서 row.c_lot 으로 사용
            "c_lot": b.lot_no,  # 또는 b.inspect_lot
            "inspect_lot": b.inspect_lot,  # 필요하면 유지
            "inspector": b.inspector,
        }
        for b in box_list
    ]

    return JsonResponse({"success": True, "results": results})