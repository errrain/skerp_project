# sales/waitinspection/views.py

from django.shortcuts import render
from django.views.decorators.http import require_GET

from production.models import WorkOrder
from quality.inspections.models import OutgoingStatus
from quality.outgoing.views import DEFAULT_BOX_SIZE  # 같은 기준 박스수 사용


@require_GET
def waitinspection_list(request):
    """
    검사대기 재고 리스트 (영업 메뉴용)

    ⚠ 날짜 조건 없이:
    - 생산완료(WorkOrder.status='완료') 인 LOT 전체에서
    - 출하검사 상태가 완료(DONE)가 아닌 것만 표시
    """

    # 1) 날짜 조건 없이, 생산완료 LOT 전체 조회
    orders_qs = (
        WorkOrder.objects
        .filter(status="완료")
        .select_related("product", "customer", "outgoing_inspection")
        .order_by("planned_start", "created_at", "id")
    )

    orders = list(orders_qs)

    # 2) outgoing_site_list 에서 계산하던 값들 그대로 얹어주기
    for o in orders:
        plan_qty = o.order_qty or 0

        # 박스당 포장수량
        product = getattr(o, "product", None)
        box_size = getattr(product, "package_quantity", None) or DEFAULT_BOX_SIZE
        o.box_size_for_outgoing = box_size

        insp = getattr(o, "outgoing_inspection", None)

        remain_qty = None          # 미검사 잔여수량
        finished_box_cnt = None    # 포장완료 BOX 수

        if insp is not None:
            adjust = insp.adjust_qty or 0
            good = insp.good_qty or 0
            defect = insp.defect_qty or 0
            loss = insp.loss_qty or 0

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

    # 3) 출하검사 미완료(DRAFT/HOLD 등) LOT만 필터링
    pending_orders = []
    for o in orders:
        insp = getattr(o, "outgoing_inspection", None)
        if insp is None or insp.status != OutgoingStatus.DONE:
            pending_orders.append(o)

    ctx = {
        "orders": pending_orders,
        # 날짜 네비게이션은 이 화면에선 안 쓰므로 안 넘김
    }
    return render(request, "waitinspection/waitinspection_list.html", ctx)
