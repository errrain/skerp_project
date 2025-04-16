from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Q
from datetime import datetime

from django.utils import timezone

from .models import InjectionOrder, InjectionOrderItem
from .forms import InjectionOrderForm, InjectionOrderItemFormSet
from .utils import generate_order_lot
from injection.models import Injection

import json

def injection_order_create(request):
    if request.method == 'POST':
        form = InjectionOrderForm(request.POST)
        if form.is_valid():
            order = form.save(commit=False)
            order.order_lot = generate_order_lot()
            order.save()

            print("✅ [ORDER 저장 완료] LOT:", order.order_lot)

            index = 0
            while True:
                inj_id = request.POST.get(f'form-{index}-injection')
                qty = request.POST.get(f'form-{index}-quantity')
                date = request.POST.get(f'form-{index}-expected_date')

                print(f"🔍 [DEBUG-{index}] inj_id={inj_id}, qty={qty}, date={date}")

                if not inj_id:
                    print(f"🛑 [BREAK] form-{index}-injection 이 없음 → 반복 종료")
                    break

                # ✅ 이 부분 추가!!
                is_checked = request.POST.get(f'form-{index}-checked')
                if not is_checked:
                    print(f"⚠️ [SKIP] form-{index} → 체크되지 않음")
                    index += 1
                    continue

                if qty and date:
                    try:
                        injection = Injection.objects.get(id=inj_id)

                        # ✅ 최신 단가 가져오기
                        latest_price_obj = injection.prices.first()
                        unit_price = latest_price_obj.price if latest_price_obj else 0
                        total_price = int(qty) * unit_price

                        InjectionOrderItem.objects.create(
                            order=order,
                            injection=injection,
                            quantity=int(qty),
                            expected_date=date,
                            unit_price=unit_price,
                            total_price=total_price
                        )
                        print(f"✅ [ITEM 저장 성공] injection={injection.alias}, qty={qty}, total={total_price}")
                    except Exception as e:
                        print(f"❌ [ITEM 저장 실패] form-{index}, 오류: {e}")
                else:
                    print(f"⚠️ [SKIP] form-{index} → 수량 또는 날짜 없음")

                index += 1

            return redirect('injectionorder:order_list')
        else:
            print("❌ [ORDER 저장 실패] form 오류:", form.errors)
    else:
        form = InjectionOrderForm()

    return render(request, 'injectionorder/order_form.html', {
        'form': form,
    })

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