# production/exec/views.py
from datetime import datetime, timedelta

from django.http import JsonResponse
from django.utils import timezone
from django.shortcuts import render, get_object_or_404   # ← get_object_or_404 추가
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET, require_POST
from django.db.models import Q

from production.models import WorkOrder
from purchase.models import InjectionReceipt, InjectionReceiptLine   # ← 사출 입고 모델 추가
from production.orders.views import _today_localdate, _day_range_for
from production.models import WorkOrder, WorkOrderInjectionUsage
from django.db import transaction


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
    return render(request, "production/exec/start_list.html", ctx)


@require_POST
def exec_start(request, pk: int):
    """
    작업 시작: 상태만 대기 → 진행중, 실제 시작시간 기록
    (사출 LOT 선택은 별도 뷰에서 처리)
    """
    wo = get_object_or_404(WorkOrder, pk=pk)

    if getattr(wo, "status", "") != "대기":
        return JsonResponse({"ok": False, "msg": "대기 상태가 아닙니다."}, status=400)

    if not getattr(wo, "actual_start", None):
        wo.actual_start = timezone.now()
    wo.status = "진행중"

    wo.save(update_fields=["status", "actual_start"])

    return JsonResponse({"ok": True})


@require_GET
def exec_injection_lot_candidates(request, pk: int):
    """
    생산진행 LOT 매칭 팝업용:
    - 대상: 선택한 작업지시(pk)의 제품(product)에 연결된 사출품(injection_item)
    - 조건:
        * InjectionReceipt: is_active=True, is_deleted=False
          (★ is_used 조건은 빼서, 이미 사용완료된 것도 다시 볼 수 있게 함)
        * InjectionReceiptLine:
            - warehouse = 'sk_wh_9' (또는 warehouse가 NULL 이면 헤더 warehouse가 sk_wh_9)
            - use_status 는 전체(미사용/부분사용/사용완료) 다 보여줌
    """
    wo = get_object_or_404(
        WorkOrder.objects.select_related("product"),
        pk=pk,
    )
    product = wo.product
    inj_item_id = getattr(product, "injection_item_id", None)

    # 제품에 사출품이 안 물려 있으면 빈 목록
    if not inj_item_id:
        return JsonResponse({"ok": True, "items": []})

    EFFECTIVE_WH = "sk_wh_9"

    # 헤더: is_used 조건 제거
    header_qs = (
        InjectionReceipt.objects
        .filter(
            is_active=True,
            is_deleted=False,
            # is_used=False,  ← 이 줄을 없앤 상태
            order__items__injection_id=inj_item_id,
        )
        .select_related("order", "warehouse")
        .order_by("-date", "-id")
        .distinct()
    )

    rec_ids = list(header_qs.values_list("id", flat=True))
    if not rec_ids:
        return JsonResponse({"ok": True, "items": []})

    # 라인: 창고만 필터, 상태는 전부 보여줌
    lines_qs = (
        InjectionReceiptLine.objects
        .filter(receipt_id__in=rec_ids)
        .select_related("warehouse", "receipt", "receipt__warehouse")
        .filter(
            Q(warehouse__warehouse_id=EFFECTIVE_WH) |
            Q(
                warehouse__isnull=True,
                receipt__warehouse__warehouse_id=EFFECTIVE_WH,
            )
        )
        .order_by("sub_seq")
    )

    items = []
    for ln in lines_qs:
        receipt = ln.receipt
        wh = ln.warehouse or receipt.warehouse
        items.append({
            "receipt_lot": getattr(receipt, "receipt_lot", ""),
            "sub_lot": ln.sub_lot,
            "qty": ln.qty,
            "use_status": ln.use_status,   # 미사용 / 부분사용 / 사용완료
            "date": (receipt.date.isoformat()
                     if getattr(receipt, "date", None) else None),
            "warehouse_name": getattr(wh, "name", ""),
            "warehouse_code": getattr(wh, "warehouse_id", ""),
        })

    return JsonResponse({"ok": True, "items": items})

@require_POST
def exec_bind_lot(request, pk: int):
    """
    사출 입고 LOT를 작업지시와 매핑 + 상태 변경 + LOT 사용이력 기록

    action:
      - use     : 사용등록  (used_qty = qty  → 사용완료)
      - cancel  : 사용취소  (used_qty = 0    → 미사용)
      - partial : 부분사용  (0 < used_qty < qty → 부분사용)
    """
    action = (request.POST.get("action") or "use").strip().lower()
    if action not in {"use", "cancel", "partial"}:
        return JsonResponse({"ok": False, "msg": "잘못된 동작입니다."}, status=400)

    # LOT 모음
    lots = [v for k, v in request.POST.items() if k.startswith("lots[")]
    if not lots:
        lots = [
            (request.POST.get(f"inbound_lot_{i}") or "").strip()
            for i in range(1, 6)
        ]
    lots = [x.strip() for x in lots if x.strip()]

    if not lots:
        return JsonResponse(
            {"ok": False, "msg": "LOT를 선택하거나 입력해 주세요."},
            status=400,
        )

    wo = get_object_or_404(WorkOrder, pk=pk)

    # 아직 대기면 사출투입 못 하게
    if getattr(wo, "status", "") == "대기":
        return JsonResponse(
            {"ok": False, "msg": "작업 시작 후 사출투입을 등록하세요."},
            status=400,
        )

    # ── 1) WorkOrder.inbound_lot 문자열 관리 (필드 있을 때만 처리) ──
    if hasattr(wo, "inbound_lot"):
        cur_str = getattr(wo, "inbound_lot") or ""
        cur = [s.strip() for s in cur_str.split(",") if s.strip()]
    else:
        cur = []

    if action in {"use", "partial"}:
        # 신규 LOT 추가 (중복 제거)
        for lot in lots:
            if lot not in cur:
                cur.append(lot)
    elif action == "cancel":
        # 선택 LOT 제거
        cur = [x for x in cur if x not in lots]

    if hasattr(wo, "inbound_lot"):
        wo.inbound_lot = ",".join(cur)
        wo.save(update_fields=["inbound_lot"])

    # ── 2) 선택된 Sub LOT 라인들 조회 ──
    lines = list(
        InjectionReceiptLine.objects
        .select_related("receipt")
        .filter(sub_lot__in=lots)
    )
    if not lines:
        return JsonResponse(
            {"ok": False, "msg": "해당 LOT를 찾을 수 없습니다."},
            status=400,
        )

    receipt_ids = set()

    # ── 3) 라인별 used_qty / use_status + 매핑 테이블 처리 ──
    for ln in lines:
        qty = ln.qty or 0

        # used_qty 계산
        if action == "use":
            new_used = qty
        elif action == "cancel":
            new_used = 0
        else:  # partial
            # 간단한 부분사용 로직: 0과 qty 사이 값으로 맞추기
            if qty <= 1:
                new_used = 0
            else:
                if 0 < (ln.used_qty or 0) < qty:
                    new_used = ln.used_qty
                elif ln.use_status == "사용완료":
                    new_used = max(qty - 1, 1)
                else:
                    new_used = 1

        # 라인 저장 (use_status 는 모델에서 자동 계산된다고 가정)
        ln.used_qty = new_used
        ln.save()   # update_fields 안 쓰고 전체 save()

        # ── 3-1) 매핑 테이블(WorkOrderInjectionUsage) 처리 ──
        if action == "cancel" or new_used == 0:
            # 사용취소거나 사용수량 0이면 매핑 삭제
            WorkOrderInjectionUsage.objects.filter(
                workorder=wo,
                line=ln,
            ).delete()
        else:
            # 사용 / 부분사용 : 사용수량 기준으로 upsert
            WorkOrderInjectionUsage.objects.update_or_create(
                workorder=wo,
                line=ln,
                defaults={"used_qty": new_used},
            )

        if ln.receipt_id:
            receipt_ids.add(ln.receipt_id)

    # ── 4) 헤더 is_used / used_at 갱신 (전 라인이 사용완료일 때만 True) ──
    for rid in receipt_ids:
        all_done = not InjectionReceiptLine.objects.filter(
            receipt_id=rid
        ).exclude(use_status="사용완료").exists()

        InjectionReceipt.objects.filter(id=rid).update(
            is_used=all_done,
            used_at=timezone.now() if all_done else None,
        )

    return JsonResponse({"ok": True})

@require_POST
def exec_cancel(request, pk: int):
    """
    작업 시작 취소:
    - 상태: '진행중' → '대기'
    - 실제 시작/종료 시간 초기화
    """
    wo = get_object_or_404(WorkOrder, pk=pk)

    if getattr(wo, "status", "") != "진행중":
        return JsonResponse({"ok": False, "msg": "진행중 상태가 아닙니다."}, status=400)

    fields = ["status"]
    wo.status = "대기"

    # 실제 시작/종료 시간 초기화 (있을 때만)
    if hasattr(wo, "actual_start"):
        wo.actual_start = None
        fields.append("actual_start")
    if hasattr(wo, "actual_end"):
        wo.actual_end = None
        fields.append("actual_end")

    wo.save(update_fields=fields)
    return JsonResponse({"ok": True})