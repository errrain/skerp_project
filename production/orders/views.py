# production/orders/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.db import transaction
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.utils.dateparse import parse_date

from vendor.models import Vendor
from product.models import Product
from django.db.models import Q

from ..models import WorkOrder
from ..forms import WorkOrderForm, WorkOrderLineFormSet
from sales.models import CustomerOrderItem  # 수주아이템

# 작업지시서 목록
def order_list(request):
    qs = WorkOrder.objects.select_related("product", "customer").all()
    keyword = (request.GET.get("q") or "").strip()
    if keyword:
        qs = qs.filter(
            Q(product__name__icontains=keyword) |
            Q(customer__name__icontains=keyword)
        )

    context = {
        "orders": qs.order_by("-created_at"),
        "keyword": keyword,
    }
    return render(request, "production/orders/order_list.html", context)

# 작업지시서 등록
@transaction.atomic
def order_create(request):
    if request.method == "POST":
        form = WorkOrderForm(request.POST)
        formset = WorkOrderLineFormSet(request.POST)

        if form.is_valid() and formset.is_valid():
            work_order = form.save(commit=False)
            work_order.created_by = request.user
            work_order.save()

            lines = formset.save(commit=False)
            for line in lines:
                line.work_order = work_order
                line.save()

            messages.success(request, f"작업지시서 {work_order.work_lot} 등록 완료")
            return redirect("production:orders:order_list")
    else:
        form = WorkOrderForm()
        formset = WorkOrderLineFormSet()

    # 수주목록 기본(최근 20)
    sales_list = (
        CustomerOrderItem.objects
        .select_related("order", "product", "order__customer")
        .filter(order__delete_yn="N")
        .order_by("-order__order_date")[:20]
    )

    # 검색 파라미터
    customer_id = (request.GET.get("customer") or "").strip()
    q = (request.GET.get("q") or "").strip()

    # 고객사 옵션
    customers = Vendor.objects.order_by("name")

    # 제품 검색(고객사/품명/품번)
    product_qs = Product.objects.select_related("customer").filter(delete_yn="N", use_yn="Y")
    if customer_id:
        product_qs = product_qs.filter(customer_id=customer_id)
    if q:
        product_qs = product_qs.filter(
            Q(name__icontains=q) |
            Q(part_number__icontains=q) |
            Q(alias__icontains=q)
        )
    search_results = product_qs.order_by("customer__name", "name")[:50]

    minute_choices = [f"{i:02d}" for i in range(60)]

    context = {
        "form": form,
        "formset": formset,
        "sales_list": sales_list,
        "customers": customers,
        "selected_customer": customer_id,
        "query": q,
        "search_results": search_results,
        "minute_choices": minute_choices,  # ✅ 추가
    }
    return render(request, "production/orders/order_form.html", context)

# 작업지시서 수정
@transaction.atomic
def order_edit(request, pk):
    work_order = get_object_or_404(WorkOrder, pk=pk)

    if request.method == "POST":
        form = WorkOrderForm(request.POST, instance=work_order)
        formset = WorkOrderLineFormSet(request.POST, instance=work_order)

        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            messages.success(request, f"작업지시서 {work_order.work_lot} 수정 완료")
            return redirect("production:orders:order_list")
    else:
        form = WorkOrderForm(instance=work_order)
        formset = WorkOrderLineFormSet(instance=work_order)

    minute_choices = [f"{i:02d}" for i in range(60)]
    context = {"form": form, "formset": formset, "work_order": work_order, "minute_choices": minute_choices,}
    return render(request, "production/orders/order_form.html", context)

# 작업지시서 삭제
@transaction.atomic
def order_delete(request, pk):
    work_order = get_object_or_404(WorkOrder, pk=pk)

    if request.method == "POST":
        work_order.delete()
        messages.success(request, f"작업지시서 {work_order.work_lot} 삭제 완료")
        return redirect("production:orders:order_list")

    return render(request, "production/orders/order_confirm_delete.html", {"work_order": work_order})

# 수주 검색(AJAX)
@require_GET
def search_sales_orders(request):
    name   = (request.GET.get("name") or "").strip()
    od_f   = request.GET.get("order_date_from")
    od_t   = request.GET.get("order_date_to")
    dd_f   = request.GET.get("delivery_date_from")
    dd_t   = request.GET.get("delivery_date_to")

    qs = CustomerOrderItem.objects.select_related("order", "product", "order__customer")

    if name:
        qs = qs.filter(
            Q(product__name__icontains=name) |
            Q(product__code__icontains=name) |    # code
            Q(product__part_number__icontains=name)  # or part_number
        )
    if od_f:
        qs = qs.filter(order__order_date__gte=parse_date(od_f))
    if od_t:
        qs = qs.filter(order__order_date__lte=parse_date(od_t))
    if dd_f:
        qs = qs.filter(delivery_date__gte=parse_date(dd_f))
    if dd_t:
        qs = qs.filter(delivery_date__lte=parse_date(dd_t))

    qs = qs.order_by("-order__order_date")[:100]

    return JsonResponse({
        "results": [
            {
                "item_id": it.id,
                "order_id": it.order_id,
                "order_date": it.order.order_date.strftime("%Y-%m-%d") if it.order.order_date else "",
                "planned_ship_date": it.delivery_date.strftime("%Y-%m-%d") if it.delivery_date else "",
                "customer_id": it.order.customer_id,
                "customer_name": getattr(it.order.customer, "name", ""),
                "product_id": it.product_id,
                "product_code": getattr(it.product, "code", "") or getattr(it.product, "part_number", ""),
                "product_name": getattr(it.product, "name", ""),
                "order_qty": it.quantity or 0,
                "injection_stock": None,
            }
            for it in qs
        ]
    })
