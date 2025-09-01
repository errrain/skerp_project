from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Q
from datetime import datetime

from django.utils import timezone

from .models import InjectionOrder, InjectionOrderItem
from .forms import InjectionOrderForm, InjectionOrderItemFormSet
from .utils import generate_order_lot
from injection.models import Injection
from django.db import transaction, IntegrityError

import json

def injection_order_create(request):
    if request.method == 'POST':
        form = InjectionOrderForm(request.POST)

        # 1) 체크된 행 수집 및 1차 검증
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

        # 2) 각 행마다 '별도 헤더(LOT)' + '품목 1건' 생성
        with transaction.atomic():
            vendor = form.cleaned_data['vendor']
            order_date = form.cleaned_data['order_date']

            for inj_id, qty, date in rows:
                # (선택) 간헐적 LOT 중복 대비 재시도 루프
                for attempt in range(3):
                    try:
                        # 헤더 생성 (개별 LOT)
                        order = InjectionOrder(
                            vendor=vendor,
                            order_date=order_date,
                            order_lot=generate_order_lot(),  # ORD+YYYYMMDD+seq
                            due_date=date,                    # 헤더 기본 예정일 정규화(선택)
                        )
                        order.save()  # unique LOT 저장

                        # 아이템 생성(1건)
                        injection = Injection.objects.get(id=inj_id)
                        latest = getattr(injection, "prices", None).first() if hasattr(injection, "prices") else None
                        unit_price = latest.price if latest else 0

                        InjectionOrderItem.objects.create(
                            order=order,
                            injection=injection,
                            quantity=qty,
                            expected_date=date,
                            unit_price=unit_price,
                            total_price=qty * unit_price,
                        )
                        break  # 성공 시 재시도 루프 탈출
                    except IntegrityError:
                        if attempt == 2:
                            raise  # 3회 실패 시 에러 전파(롤백)
                        # 재시도: 다음 루프로 진입하여 LOT 다시 생성
                        continue

        return redirect('injectionorder:order_list')

    # GET
    form = InjectionOrderForm()
    return render(request, 'injectionorder/order_form.html', {'form': form})

def order_list(request):
    items = InjectionOrderItem.objects.select_related(
        'order', 'injection', 'order__vendor'
    ).filter(order__dlt_yn='N').order_by('-order__order_date')

    # 검색 필터
    order_date_start = request.GET.get('order_date_start')
    order_date_end = request.GET.get('order_date_end')
    expected_date_start = request.GET.get('expected_date_start')
    expected_date_end = request.GET.get('expected_date_end')
    vendor_name = request.GET.get('vendor')
    product_name = request.GET.get('product')

    if order_date_start:
        items = items.filter(order__order_date__gte=order_date_start)
    if order_date_end:
        items = items.filter(order__order_date__lte=order_date_end)
    if expected_date_start:
        items = items.filter(expected_date__gte=expected_date_start)
    if expected_date_end:
        items = items.filter(expected_date__lte=expected_date_end)
    if vendor_name:
        items = items.filter(order__vendor__name__icontains=vendor_name)
    if product_name:
        items = items.filter(injection__name__icontains=product_name)

    return render(request, 'injectionorder/order_list.html', {
        'order_items': items
    })

def get_injections_by_vendor(request):
    vendor_id = request.GET.get('vendor_id')
    if not vendor_id:
        return JsonResponse({'error': 'No vendor_id provided'}, status=400)

    try:
        injections = Injection.objects.filter(vendor_id=vendor_id, use_yn='Y', delete_yn='N')
        data = []
        for inj in injections:
            data.append({
                'id': inj.id,
                'alias': inj.alias,
                'name': inj.name,
                'current_stock': inj.current_stock if hasattr(inj, 'current_stock') else '',
                'today': timezone.now().strftime('%Y-%m-%d')
            })
        return JsonResponse({'injections': data})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


def injection_order_edit(request, order_id):
    order = get_object_or_404(InjectionOrder, id=order_id)
    items = InjectionOrderItem.objects.filter(order=order).select_related('injection')

    if request.method == 'POST':
        form = InjectionOrderForm(request.POST, instance=order)
        if form.is_valid():
            form.save()

            # 기존 아이템 전부 삭제 후 재등록
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
                    try:
                        injection = Injection.objects.get(id=inj_id)
                        latest_price = injection.prices.first()
                        unit_price = latest_price.price if latest_price else 0
                        total_price = int(qty) * unit_price

                        InjectionOrderItem.objects.create(
                            order=order,
                            injection=injection,
                            quantity=int(qty),
                            expected_date=date,
                            unit_price=unit_price,
                            total_price=total_price
                        )
                    except Exception as e:
                        print(f"❌ [ITEM 저장 실패] form-{index}, 오류: {e}")
                else:
                    print(f"⚠️ [SKIP] form-{index} → 수량 또는 날짜 없음")

                index += 1

            return redirect('injectionorder:order_list')
        else:
            print("❌ [ORDER 수정 실패] form 오류:", form.errors)
    else:
        form = InjectionOrderForm(instance=order)

    # JSON으로 넘길 기존 항목 데이터 구성
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
        'existing_items_json': json.dumps(existing_items),  # ✅ 이름 통일!
    })