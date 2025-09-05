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
    order = get_object_or_404(
        InjectionOrder.objects.select_related("vendor").prefetch_related("items"),
        pk=order_id
    )

    # ── 유틸 (이미 있으시면 기존 것 사용)
    def to_date_or_none(s):
        try:
            return datetime.strptime(s.strip(), "%Y-%m-%d").date() if s else None
        except Exception:
            return None

    def to_int_or_none(s):
        try:
            return int(s) if s not in (None, "") else None
        except Exception:
            return None

    # ── 발주 총 수량
    qty_sum = order.items.aggregate(s=Sum("quantity"))["s"] or 0

    # ── 폼 입력값 파싱
    inspection_date = to_date_or_none(request.POST.get("inspection_date"))
    status          = (request.POST.get("status") or "").strip()  # '대기/합격/불합격/보류'
    defects         = request.POST.getlist("defects")  # ArrayField
    production_date1 = to_date_or_none(request.POST.get("production_date1"))
    production_qty1  = to_int_or_none(request.POST.get("production_qty1")) or 0
    production_date2 = to_date_or_none(request.POST.get("production_date2"))
    production_qty2  = to_int_or_none(request.POST.get("production_qty2")) or 0
    production_date3 = to_date_or_none(request.POST.get("production_date3"))
    production_qty3  = to_int_or_none(request.POST.get("production_qty3")) or 0
    inspect_qty      = to_int_or_none(request.POST.get("inspect_qty")) or 0
    return_qty       = to_int_or_none(request.POST.get("return_qty")) or 0
    remark           = (request.POST.get("remark") or "").strip()

    # ── 검증 규칙
    errors = []

    # (1) 필수값
    if not inspection_date:
        errors.append("검사일은 필수입니다.")
    if not status:
        errors.append("검사 상태는 필수입니다.")

    # (2) 수량 형식/범위
    if inspect_qty < 0:
        errors.append("검사 수량은 음수가 될 수 없습니다.")
    if return_qty < 0:
        errors.append("반출(반품) 수량은 음수가 될 수 없습니다.")

    # (3) 검사수량 <= 발주총수량
    if inspect_qty > qty_sum:
        errors.append(f"검사 수량({inspect_qty})이 발주 수량합({qty_sum})을 초과할 수 없습니다.")

    # (4) 반출수량 <= 검사수량
    if return_qty > inspect_qty:
        errors.append(f"반출(반품) 수량({return_qty})은 검사 수량({inspect_qty})을 초과할 수 없습니다.")

    # (5) 생산일/수량 쌍 검증 (둘 중 하나만 있는 경우 경고)
    def pair_check(d, q, idx):
        if (d and q == 0) or (not d and q > 0):
            errors.append(f"생산({idx})은 날짜와 수량을 함께 입력해야 합니다.")
    pair_check(production_date1, production_qty1, "1")
    pair_check(production_date2, production_qty2, "2")
    pair_check(production_date3, production_qty3, "3")

    # (6) 상태별 규칙: 불합격/보류는 불량사유 필수
    if status in ("불합격", "보류") and len(defects) == 0:
        errors.append("불합격 또는 보류 상태에서는 불량 사유를 1개 이상 선택해야 합니다.")

    # (7) 자동 상태 전환 규칙
    # - 반출수량이 있는 경우 '합격'을 선택했더라도 '불합격'으로 자동 전환
    auto_status_note = None
    if return_qty > 0 and status == "합격":
        status = "불합격"
        auto_status_note = "반출(반품) 수량이 있어 상태를 '불합격'으로 자동 변경했습니다."

    # 유효성 오류가 있으면 폼 재표시 (사용자 입력값을 그대로 프리필)
    if errors:
        for e in errors:
            messages.error(request, e)
        # 템플릿은 'insp' 객체의 속성으로 프리필하므로, 임시 네임스페이스를 만들어 전달
        insp_prefill = SimpleNamespace(
            inspection_date=inspection_date,
            status=status,
            defects=defects,
            production_date1=production_date1, production_qty1=production_qty1,
            production_date2=production_date2, production_qty2=production_qty2,
            production_date3=production_date3, production_qty3=production_qty3,
            inspect_qty=inspect_qty,
            return_qty=return_qty,
            remark=remark,
        )
        # 목록 카드 상단 표시 정보
        first_item = order.items.first()
        product_name = first_item.injection.name if first_item and first_item.injection else "-"

        ctx = {
            "order": order,
            "qty_sum": qty_sum,
            "product_name": product_name,
            "status_choices": QCStatus.choices,
            "defect_choices": DEFECT_CODE_CHOICES,
            "insp": insp_prefill,
            "today": date.today(),
        }
        return render(request, "quality/incoming/inspect_modal.html", ctx)

    # ── 저장(현재 정책: 히스토리 누적 방식 -> 항상 신규 생성)
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

    if auto_status_note:
        messages.info(request, auto_status_note)
    messages.success(request, "수입검사가 저장되었습니다.")
    return redirect("quality:incoming_list")
# ---------------------------------------------------------------
