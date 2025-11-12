# production/finish/views.py
from datetime import timedelta

from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.utils.dateparse import parse_date
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from production.models import WorkOrder, WorkOrderInjectionUsage

from production.models import WorkOrder
from production.orders.views import _today_localdate, _day_range_for

from purchase.models import InjectionReceiptLine
from production.models import WorkOrder

@require_GET
def finish_list(request):
    """
    생산완료(현장용) 리스트
    - exec_list 와 비슷하게, 날짜별 작업지시 보여주기
    """
    d_str = (request.GET.get("d") or "").strip()
    try:
        query_date = parse_date(d_str) if d_str else _today_localdate()
    except Exception:
        query_date = _today_localdate()

    start_dt, end_dt = _day_range_for(query_date)

    qs = (
        WorkOrder.objects
        .filter(planned_start__gte=start_dt, planned_start__lt=end_dt)
        .select_related("product", "customer")
        .order_by("planned_start", "created_at", "id")
    )

    ctx = {
        "orders": qs,
        "query_date": query_date,
        "prev_date": query_date - timedelta(days=1),
        "next_date": query_date + timedelta(days=1),
    }
    return render(request, "production/finish/finish_list.html", ctx)

@require_POST
def finish_done(request, pk: int):
    """
    작업 종료 처리:
    - 상태: '진행중' → '완료'
    - 실제 종료 시간(actual_end) 기록
    """
    wo = get_object_or_404(WorkOrder, pk=pk)

    if wo.status != "진행중":
        return JsonResponse(
            {"ok": False, "msg": "진행중 상태가 아닙니다."},
            status=400,
        )

    # 시작시간이 비어 있으면 지금 시각으로 채워주기(선택사항)
    if not wo.actual_start:
        wo.actual_start = timezone.now()

    wo.actual_end = timezone.now()
    wo.status = "완료"
    wo.save(update_fields=["status", "actual_start", "actual_end"])

    return JsonResponse({"ok": True})

@require_POST
def finish_revert(request, pk: int):
    """
    작업 완료 취소:
    - 상태: '완료' → '진행중'
    - 실제 종료 시간(actual_end) 초기화
    """
    wo = get_object_or_404(WorkOrder, pk=pk)

    if wo.status != "완료":
        return JsonResponse(
            {"ok": False, "msg": "완료 상태가 아닙니다."},
            status=400,
        )

    # 시작시간은 유지, 종료시간만 지움
    wo.status = "진행중"
    wo.actual_end = None
    wo.save(update_fields=["status", "actual_end"])

    return JsonResponse({"ok": True})

@require_GET
@require_GET
def finish_print(request, pk: int):
    order = get_object_or_404(
        WorkOrder.objects.select_related("product"),
        pk=pk,
    )

    usages = (
        WorkOrderInjectionUsage.objects
        .filter(workorder=order)
        .select_related(
            "line",
            "line__receipt",
            "line__warehouse",
            "line__receipt__warehouse",
        )
        .order_by("line__receipt__date", "line__receipt_id", "line__sub_seq")
    )

    # 템플릿에서는 InjectionReceiptLine 만 쓰게 하고 싶으면 이렇게 가공
    lines = [u.line for u in usages]

    ctx = {
        "order": order,
        "lines": lines,
    }
    return render(request, "production/finish/print_sheet.html", ctx)