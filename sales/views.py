# sales/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.contrib import messages
from django.utils import timezone
from .models import CustomerOrder, CustomerOrderItem
from .forms import CustomerOrderForm
from product.models import Product, ProductPrice
from django.db.models import Q, Count, Sum
from django.db import transaction


def order_create(request):
    if request.method == 'POST':
        print("📥 [POST 요청 수신] request.POST.dict():")
        for key, val in request.POST.items():
            print(f"   🔸 {key} = {val}")

        form = CustomerOrderForm(request.POST)

        if form.is_valid():
            print("✅ [폼 유효성 통과] CustomerOrderForm OK")
            try:
                with transaction.atomic():
                    order = form.save(commit=False)
                    order.created_by = request.user.username
                    order.save()
                    print(f"✅ [ORDER 저장 성공] ID={order.id} / 고객사={order.customer}")

                    index = 0
                    while True:
                        product_id = request.POST.get(f'form-{index}-product')
                        qty = request.POST.get(f'form-{index}-quantity')
                        date = request.POST.get(f'form-{index}-delivery_date')
                        invoice = request.POST.get(f'form-{index}-invoice')

                        print(f"🔍 [ITEM-{index}] product={product_id}, qty={qty}, date={date}, invoice={invoice}")

                        if not product_id:
                            print(f"🛑 [종료] product_id 없음 → 반복 중단 (index={index})")
                            break

                        if qty and date:
                            CustomerOrderItem.objects.create(
                                order=order,
                                product_id=product_id,
                                quantity=qty,
                                delivery_date=date,
                                invoice_number=invoice or None,
                                created_by=request.user.username,
                            )
                            print(f"✅ [ITEM 저장 성공] → product_id={product_id}")
                        else:
                            print(f"⚠️ [ITEM 저장 SKIP] index={index} → 수량/출하일 누락")

                        index += 1

                print("✅ [전체 저장 완료] Redirect to order_list")
                return redirect('sales:order_list')

            except Exception as e:
                print(f"❌ [예외 발생] 저장 중 오류 → {e}")

        else:
            print("❌ [폼 오류 발생]")
            for field, errors in form.errors.items():
                print(f"   ❗ {field}: {errors}")

    else:
        print("📥 [GET 요청] 수주 등록 화면 진입")
        form = CustomerOrderForm()

    return render(request, 'sales/order_form.html', {
        'form': form
    })


def order_list(request):
    items = CustomerOrderItem.objects.select_related(
        'order', 'product', 'order__customer'
    ).filter(order__delete_yn='N')

    customer = request.GET.get('customer')
    part = request.GET.get('part')
    name = request.GET.get('name')

    if customer:
        items = items.filter(order__customer__name__icontains=customer)
    if part:
        items = items.filter(product__part_number__icontains=part)
    if name:
        items = items.filter(product__name__icontains=name)

    items = items.order_by('-order__order_date')

    return render(request, 'sales/order_list.html', {
        'items': items,
        'filter': {
            'customer': customer or '',
            'part': part or '',
            'name': name or '',
        }
    })


def search_products(request):
    customer_id = request.GET.get('customer_id')
    part = request.GET.get('part', '')
    name = request.GET.get('name', '')
    alias = request.GET.get('alias', '')

    q = Q(customer_id=customer_id) & (
        Q(part_number__icontains=part) |
        Q(name__icontains=name) |
        Q(alias__icontains=alias)
    )

    products = Product.objects.filter(q, use_yn='Y', delete_yn='N')[:20]

    return JsonResponse({'products': [
        {
            'id': p.id,
            'part_number': p.part_number,
            'name': p.name,
            'price': p.prices.first().price if p.prices.exists() else 0,
            'customer_name': p.customer.name
        } for p in products
    ]})

def order_edit(request, pk):
    order = get_object_or_404(CustomerOrder, pk=pk)
    form = CustomerOrderForm(instance=order)

    # 추후 수주 상세 항목도 함께 전달 필요 시 수정 가능
    return render(request, 'sales/order_form.html', {
        'form': form,
        'edit_mode': True,
        'order': order,
    })

def order_delete(request, pk):
    order = get_object_or_404(CustomerOrder, pk=pk)
    order.delete_yn = 'Y'
    order.updated_by = request.user.username
    order.save()
    print(f"🗑️ 수주 삭제 완료 → ID={order.id}")
    return redirect('sales:order_list')