from django.shortcuts import render, get_object_or_404, redirect
from django.db.models import Sum
from django.views.decorators.http import require_http_methods
from django.contrib import messages
from datetime import datetime, date
from django.db.models import OuterRef, Subquery, Case, When, Value, CharField, DateTimeField

from injectionorder.models import InjectionOrder
from .inspections.models import IncomingInspection, QCStatus, DEFECT_CODE_CHOICES


def incoming_list(request):
    """
    수입검사 목록:
    - 구매 발주 중 '입고대기'만 대상
    - 최신 수입검사 상태/일시 주석
    - 기본 검색 필터 지원
    """
    # 기본 쿼리 + 검색 필터
    qs = InjectionOrder.objects.filter(status='입고대기', dlt_yn='N').select_related('vendor')

    order_date_start = request.GET.get('order_date_start')
    order_date_end   = request.GET.get('order_date_end')
    expected_date_start = request.GET.get('expected_date_start')
    expected_date_end   = request.GET.get('expected_date_end')
    vendor_name = request.GET.get('vendor')
    product_name = request.GET.get('product')

    if order_date_start:    qs = qs.filter(order_date__gte=order_date_start)
    if order_date_end:      qs = qs.filter(order_date__lte=order_date_end)
    if expected_date_start: qs = qs.filter(due_date__gte=expected_date_start)
    if expected_date_end:   qs = qs.filter(due_date__lte=expected_date_end)
    if vendor_name:         qs = qs.filter(vendor__name__icontains=vendor_name)
    if product_name:        qs = qs.filter(items__injection__name__icontains=product_name)

    # 수량 합계(품목 테이블 조인) + 최신 검사 상태/일시 주석
    latest_insp_qs = (
        IncomingInspection.objects
        .filter(order=OuterRef('pk'))
        .order_by('-created_at', '-id')
    )

    qs = (
        qs.prefetch_related('items')
          .annotate(qty_sum=Sum('items__quantity'))
          .annotate(
              insp_status=Subquery(latest_insp_qs.values('status')[:1]),
              insp_date=Subquery(
                  latest_insp_qs.values('created_at')[:1],
                  output_field=DateTimeField()
              ),
          )
          .annotate(
              insp_status_display=Case(
                  When(insp_status=QCStatus.DRAFT, then=Value("대기")),
                  When(insp_status=QCStatus.PASS,  then=Value("합격")),
                  When(insp_status=QCStatus.FAIL,  then=Value("불합격")),
                  When(insp_status=QCStatus.HOLD,  then=Value("보류")),
                  default=Value("미실시"),
                  output_field=CharField(),
              )
          )
          .order_by('-order_date', '-id')
          .distinct()
    )

    return render(request, "quality/incoming/list.html", {"orders": qs})


@require_http_methods(["GET"])
def incoming_inspect_layer(request, order_id: int):
    # 발주 + 연관 정보 최적화 조회
    order = get_object_or_404(
        InjectionOrder.objects
        .select_related("vendor")
        .prefetch_related("items__injection"),
        pk=order_id
    )

    # 발주 수량 합계
    qty_sum = order.items.aggregate(s=Sum("quantity"))["s"] or 0

    # 대표 품명(첫 아이템 기준)
    first_item = order.items.first()
    product_name = first_item.injection.name if first_item and first_item.injection else "-"

    # 최신 검사 1건 (있으면 수정 프리필, 없으면 신규 입력 상태)
    insp = (
        IncomingInspection.objects
        .filter(order=order)
        .order_by("-created_at", "-id")
        .first()
    )

    ctx = {
        "order": order,
        "qty_sum": qty_sum,
        "product_name": product_name,
        "status_choices": QCStatus.choices,
        "defect_choices": DEFECT_CODE_CHOICES,
        "insp": insp,           # ✅ 템플릿에서 value/selected/checked 프리필에 사용
        "today": date.today(),  # ✅ 기본 날짜 표시용
    }
    return render(request, "quality/incoming/inspect_modal.html", ctx)


@require_http_methods(["POST"])
def incoming_inspect_save(request, order_id: int):
    """
    수입검사 저장 처리:
    - 날짜 문자열은 안전 파싱(빈 값/잘못된 형식 → None)
    - 수량 필드는 정수 변환(빈 값 → None)
    - defects 는 체크박스 다중값 리스트로 수신
    """
    order = get_object_or_404(InjectionOrder, pk=order_id)

    # ---- helper ----
    def to_date_or_none(v: str | None):
        if not v:
            return None
        try:
            return datetime.strptime(v, "%Y-%m-%d").date()
        except ValueError:
            return None

    def to_int_or_none(v: str | None):
        try:
            return int(v) if v not in (None, "",) else None
        except (TypeError, ValueError):
            return None
    # ---------------

    # 날짜 필드: 빈 문자열이면 None, 메인 검사일은 값 없으면 오늘 날짜로 대체
    inspection_date  = to_date_or_none(request.POST.get("inspection_date")) or date.today()
    production_date1 = to_date_or_none(request.POST.get("production_date1"))
    production_date2 = to_date_or_none(request.POST.get("production_date2"))
    production_date3 = to_date_or_none(request.POST.get("production_date3"))

    # 수량 필드
    production_qty1  = to_int_or_none(request.POST.get("production_qty1"))
    production_qty2  = to_int_or_none(request.POST.get("production_qty2"))
    production_qty3  = to_int_or_none(request.POST.get("production_qty3"))
    inspect_qty      = to_int_or_none(request.POST.get("inspect_qty"))
    return_qty       = to_int_or_none(request.POST.get("return_qty"))

    # 상태/불량 사유/비고
    status   = request.POST.get("status") or QCStatus.DRAFT
    defects  = request.POST.getlist("defects")  # 다중 체크박스
    remark   = request.POST.get("remark") or ""

    # 저장
    IncomingInspection.objects.create(
        order=order,
        inspection_date=inspection_date,
        production_date1=production_date1, production_qty1=production_qty1,
        production_date2=production_date2, production_qty2=production_qty2,
        production_date3=production_date3, production_qty3=production_qty3,
        status=status,
        defects=defects,
        inspect_qty=inspect_qty,
        return_qty=return_qty,
        remark=remark,
    )

    messages.success(request, "수입검사가 저장되었습니다.")
    return redirect("quality:incoming_list")
