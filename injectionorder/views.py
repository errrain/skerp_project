# injectionorder/views.py (patched)
import csv
import json
from datetime import datetime, timedelta
from datetime import date

from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator

from .models import InjectionOrder, InjectionOrderItem, OrderStatus, FlowStatus
from .forms import InjectionOrderForm
from utils.lot import get_next_lot
from injection.models import Injection

# =========================
# 유틸
# =========================
def _parse_date(s: str):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _latest_unit_price(injection) -> int:
    """
    injection.prices(단가 히스토리)에서 최신 단가를 안전하게 가져온다.
    - 필드 존재 우선순위: created_dt -> date -> id
    """
    if not hasattr(injection, "prices"):
        return 0
    qs = injection.prices.all()
    field_names = {f.name for f in qs.model._meta.get_fields()}
    if "created_dt" in field_names:
        obj = qs.order_by("-created_dt").first()
    elif "date" in field_names:
        obj = qs.order_by("-date").first()
    else:
        obj = qs.order_by("-id").first()
    return obj.price if obj else 0


# =========================
# 발주 등록
# =========================
@login_required
@transaction.atomic
def injection_order_create(request):
    if request.method == 'POST':
        form = InjectionOrderForm(request.POST)

        # 선택 행 수집
        rows = []
        idx = 0
        while True:
            inj_id = request.POST.get(f'form-{idx}-injection')
            if not inj_id:
                break
            if request.POST.get(f'form-{idx}-checked'):
                qty = request.POST.get(f'form-{idx}-quantity')
                date = request.POST.get(f'form-{idx}-expected_date')
                if not qty or not str(qty).isdigit() or int(qty) <= 0 or not date:
                    form.add_error(None, f"{idx+1}행: 수량/입고예정일을 확인하세요.")
                else:
                    rows.append((inj_id, int(qty), date))
            idx += 1

        if not rows:
            form.add_error(None, "발주 품목을 1개 이상 선택하세요.")

        if not form.is_valid():
            return render(request, 'injectionorder/order_form.html', {'form': form})

        # 행마다 개별 헤더(LOT) + 품목 1건 생성
        vendor = form.cleaned_data['vendor']
        order_date = form.cleaned_data['order_date']

        for inj_id, qty, date in rows:
            order = InjectionOrder(
                vendor=vendor,
                order_date=order_date,
                order_lot=get_next_lot('OR', anchor_dt=order_date),
                due_date=date,
                created_by=request.user,
                order_status=OrderStatus.NEW,
                flow_status=FlowStatus.NG,
            )
            order.save()

            injection = get_object_or_404(Injection, id=inj_id)
            unit_price = _latest_unit_price(injection)

            InjectionOrderItem.objects.create(
                order=order,
                injection=injection,
                quantity=qty,
                expected_date=date,
                unit_price=unit_price,
                total_price=qty * unit_price,
                created_by=request.user,
            )

        return redirect('injectionorder:order_list')

    form = InjectionOrderForm()
    return render(request, 'injectionorder/order_form.html', {'form': form})


# =========================
# 발주 목록
# =========================
@login_required
def order_list(request):
    items = (InjectionOrderItem.objects
             .select_related('order', 'injection', 'order__vendor',
                             'order__created_by', 'order__updated_by')
             .filter(order__dlt_yn='N')
             .order_by('-order__order_date'))

    # 📅 기본 월 범위 계산 (이번 달 1일 ~ 말일)
    today = date.today()
    month_start = today.replace(day=1)
    if today.month == 12:
        month_end = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
    else:
        month_end = today.replace(month=today.month + 1, day=1) - timedelta(days=1)

    # ─ 검색 파라미터
    order_date_start = _parse_date(request.GET.get('order_date_start')) or month_start
    order_date_end = _parse_date(request.GET.get('order_date_end')) or month_end
    expected_date_start = _parse_date(request.GET.get('expected_date_start')) or month_start
    expected_date_end = _parse_date(request.GET.get('expected_date_end')) or month_end
    vendor_name = (request.GET.get('vendor') or '').strip()
    product_name = (request.GET.get('product') or '').strip()
    order_status = (request.GET.get('order_status') or '').strip()
    flow_status = (request.GET.get('flow_status') or '').strip()

    # 📌 날짜 필터: 발주일 범위 OR 입고예정일 범위
    date_q = (
        Q(order__order_date__range=(order_date_start, order_date_end)) |
        Q(expected_date__range=(expected_date_start, expected_date_end))
    )
    items = items.filter(date_q)

    if vendor_name:
        items = items.filter(order__vendor__name__icontains=vendor_name)
    if product_name:
        items = items.filter(injection__name__icontains=product_name)
    if order_status:
        items = items.filter(order__order_status=order_status)
    if flow_status:
        items = items.filter(order__flow_status=flow_status)

    # 페이징
    page = request.GET.get('page', 1)
    paginator = Paginator(items, 20)
    page_obj = paginator.get_page(page)

    def _qs_without_page():
        qd = request.GET.copy()
        qd.pop('page', None)
        return qd.urlencode()

    return render(request, 'injectionorder/order_list.html', {
        'order_items': page_obj,
        'page_obj': page_obj,
        'querystring': _qs_without_page(),
        'order_status_choices': OrderStatus.choices,
        'flow_status_choices': FlowStatus.choices,
        # 입력 기본값 세팅용 (최초 진입 시에도 값이 채워져 보이도록)
        'order_date_start_default': order_date_start.strftime('%Y-%m-%d'),
        'order_date_end_default': order_date_end.strftime('%Y-%m-%d'),
        'expected_date_start_default': expected_date_start.strftime('%Y-%m-%d'),
        'expected_date_end_default': expected_date_end.strftime('%Y-%m-%d'),
    })

# 🟢 엑셀(CSV) 다운로드: 페이징 무시, 검색조건 동일 적용
@login_required
def order_export(request):
    qs = (InjectionOrderItem.objects
          .select_related('order', 'injection', 'order__vendor',
                          'order__created_by', 'order__updated_by')
          .filter(order__dlt_yn='N'))

    # 이번 달 1일~말일 기본값 (views.list와 동일 로직)
    today = date.today()
    month_start = today.replace(day=1)
    if today.month == 12:
        month_end = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
    else:
        month_end = today.replace(month=today.month + 1, day=1) - timedelta(days=1)

    # 검색값 해석 (없으면 기본값 적용)
    def _parse_date(s):
        from datetime import datetime
        try:
            return datetime.strptime(s, "%Y-%m-%d").date()
        except Exception:
            return None

    order_date_start = _parse_date(request.GET.get('order_date_start')) or month_start
    order_date_end = _parse_date(request.GET.get('order_date_end')) or month_end
    expected_date_start = _parse_date(request.GET.get('expected_date_start')) or month_start
    expected_date_end = _parse_date(request.GET.get('expected_date_end')) or month_end
    vendor_name = (request.GET.get('vendor') or '').strip()
    product_name = (request.GET.get('product') or '').strip()
    order_status = (request.GET.get('order_status') or '').strip()
    flow_status = (request.GET.get('flow_status') or '').strip()

    qs = qs.filter(
        Q(order__order_date__range=(order_date_start, order_date_end)) |
        Q(expected_date__range=(expected_date_start, expected_date_end))
    )
    if vendor_name:
        qs = qs.filter(order__vendor__name__icontains=vendor_name)
    if product_name:
        qs = qs.filter(injection__name__icontains=product_name)
    if order_status:
        qs = qs.filter(order__order_status=order_status)
    if flow_status:
        qs = qs.filter(order__flow_status=flow_status)

    # ---------- CSV 응답 (UTF-8 BOM 추가로 한글 깨짐 방지) ----------
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    filename = f"injection_orders_{today.strftime('%Y%m%d')}.csv"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    # ★ Excel용 BOM (UTF-8-SIG)
    response.write('\ufeff')

    writer = csv.writer(response, lineterminator='\n')

    writer.writerow([
        '발주LOT','발주처','발주일','품명','수량','입고예정일',
        '발주상태','진행상태','취소일시','취소자',
        '등록일시','등록자','수정일시','수정자','단가','합계금액'
    ])

    def dstr(d):   # date -> 'YYYY-MM-DD' or '-'
        return d.strftime('%Y-%m-%d') if d else '-'

    def dtstr(dt): # datetime -> 'YYYY-MM-DD HH:MM' or '-'
        return dt.strftime('%Y-%m-%d %H:%M') if dt else '-'

    def ustr(u):   # user -> full_name/username or '-'
        if not u:
            return '-'
        return getattr(u, 'full_name', '') or getattr(u, 'username', '') or '-'

    for it in qs:
        o = it.order
        writer.writerow([
            o.order_lot or '-',
            getattr(o.vendor, 'name', '-') or '-',
            dstr(o.order_date),
            getattr(it.injection, 'name', '-') or '-',
            it.quantity if it.quantity is not None else 0,
            dstr(it.expected_date),

            o.get_order_status_display() or '-',
            o.get_flow_status_display() or '-',
            dtstr(o.cancel_at),
            ustr(o.cancel_by),

            dtstr(o.created_at),
            ustr(o.created_by),
            dtstr(o.updated_at),
            ustr(o.updated_by),

            it.unit_price if it.unit_price is not None else 0,
            it.total_price if it.total_price is not None else 0,
        ])

    return response

# =========================
# 발주 수정
# =========================
@login_required
@transaction.atomic
def injection_order_edit(request, order_id):
    order = get_object_or_404(InjectionOrder, id=order_id)
    items = InjectionOrderItem.objects.filter(order=order).select_related('injection')

    if request.method == 'POST':
        form = InjectionOrderForm(request.POST, instance=order)
        if form.is_valid():
            order = form.save(commit=False)
            order.updated_by = request.user
            order.save()

            InjectionOrderItem.objects.filter(order=order).delete()

            index = 0
            while True:
                inj_id = request.POST.get(f'form-{index}-injection')
                qty = request.POST.get(f'form-{index}-quantity')
                date = request.POST.get(f'form-{index}-expected_date')
                is_checked = request.POST.get(f'form-{index}-checked')
                if not inj_id:
                    break

                if is_checked and qty and date:
                    injection = get_object_or_404(Injection, id=inj_id)
                    unit_price = _latest_unit_price(injection)

                    InjectionOrderItem.objects.create(
                        order=order,
                        injection=injection,
                        quantity=int(qty),
                        expected_date=date,
                        unit_price=unit_price,
                        total_price=int(qty) * unit_price,
                        created_by=request.user,
                    )
                index += 1

            return redirect('injectionorder:order_list')
    else:
        form = InjectionOrderForm(instance=order)

    existing_items = [
        {
            "injection": {
                "id": item.injection.id,
                "name": item.injection.name,
                "alias": item.injection.alias,
            },
            "quantity": item.quantity,
            "expected_date": item.expected_date.strftime('%Y-%m-%d'),
        }
        for item in items
    ]

    return render(request, 'injectionorder/order_form.html', {
        'form': form,
        'edit_mode': True,
        'order_id': order.id,
        'existing_items_json': json.dumps(existing_items),
    })


# =========================
# 발주 취소 (기존 delete 대체)
# =========================
@login_required
@require_POST
def order_cancel(request, order_id):
    order = get_object_or_404(InjectionOrder, id=order_id, dlt_yn='N')
    if not order.can_cancel:
        # 이미 취소되었거나 입고 진행 중이면 취소 불가
        return redirect('injectionorder:order_list')

    order.mark_cancelled(user=request.user, reason="사용자 요청 취소")
    return redirect('injectionorder:order_list')


# =========================
# 협력사별 사출품 목록 반환(AJAX)
# =========================
@login_required
def get_injections_by_vendor(request):
    vendor_id = request.GET.get('vendor_id')
    if not vendor_id:
        return JsonResponse({'injections': []})

    qs = Injection.objects.filter(
        vendor_id=vendor_id, use_yn='Y', delete_yn='N'
    ).values('id', 'alias', 'name')

    today = timezone.now().strftime('%Y-%m-%d')
    data = [
        {'id': r['id'], 'alias': r['alias'], 'name': r['name'], 'today': today}
        for r in qs
    ]
    return JsonResponse({'injections': data})