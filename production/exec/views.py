# production/exec/views.py
from datetime import datetime, timedelta

from django.http import JsonResponse
from django.shortcuts import render
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET, require_POST
from django.db.models import Q

from production.models import WorkOrder
# 기존 orders 모듈의 날짜 유틸 재사용 (오늘/일자범위) → order_list와 동일 흐름
from production.orders.views import _today_localdate, _day_range_for  # [ref] orders.views 유틸 재사용

@require_GET
def exec_list(request):
    """
    생산진행(현장용) – 최초 출력은 '오늘'
    - 쿼리스트링 d=YYYY-MM-DD 있을 경우 해당 일자
    - 컨텍스트 키: orders, query_date, prev_date, next_date (order_list와 동일)
    """
    # 날짜 파싱: 없으면 오늘
    d_str = (request.GET.get("d") or "").strip()
    try:
        query_date = parse_date(d_str) if d_str else _today_localdate()
    except Exception:
        query_date = _today_localdate()

    start_dt, end_dt = _day_range_for(query_date)

    # 목록: 당일 planned_start 범위, product/customer 정보 포함
    qs = (WorkOrder.objects
          .filter(planned_start__gte=start_dt, planned_start__lt=end_dt)
          .select_related("product", "customer")
          .order_by("planned_start", "created_at", "id"))

    ctx = {
        "orders": qs,
        "query_date": query_date,
        "prev_date": query_date - timedelta(days=1),
        "next_date": query_date + timedelta(days=1),
    }
    return render(request, "production/exec/start_list.html", ctx)


def exec_start(request, pk: int):
    lots = [v for k, v in request.POST.items() if k.startswith("lots[")]
    if not lots:
        # 폴백: inbound_lot_1..5
        lots = [request.POST.get(f"inbound_lot_{i}", "").strip() for i in range(1, 6)]
    lots = [x.strip() for x in lots if x and x.strip()]
    joined = ",".join(lots) if lots else ""

    wo = get_object_or_404(WorkOrder, pk=pk)
    if getattr(wo, "status", "") != "대기":
        return JsonResponse({"ok": False, "msg": "대기 상태가 아닙니다."}, status=400)

    if hasattr(wo, "inbound_lot"):
        wo.inbound_lot = joined
    wo.status = "진행중"
    if not getattr(wo, "actual_start", None):
        wo.actual_start = timezone.now()
    wo.save(update_fields=[*(["inbound_lot"] if hasattr(wo, "inbound_lot") else []),
                           "status", "actual_start"])
    return JsonResponse({"ok": True})