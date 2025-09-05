from django.shortcuts import render, redirect, get_object_or_404
from django.db import transaction
from django.contrib import messages

from vendor.models import Vendor           # 고객사(거래처)
from product.models import Product         # 제품
from django.db.models import Q             # 검색용

from ..models import WorkOrder
from ..forms import WorkOrderForm, WorkOrderLineFormSet
from sales.models import CustomerOrderItem  # ✅ CustomerOrderItem 사용

# 작업지시서 목록
def order_list(request):
    qs = WorkOrder.objects.select_related("product", "customer").all()
    keyword = request.GET.get("q")
    if keyword:
        qs = qs.filter(product__name__icontains=keyword) | qs.filter(customer__name__icontains=keyword)

    context = {
        "orders": qs.order_by("-created_at"),
        "keyword": keyword or "",
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

            # 라인 저장 (외래키 연결)
            lines = formset.save(commit=False)
            for line in lines:
                line.work_order = work_order
                line.save()

            messages.success(request, f"작업지시서 {work_order.work_lot} 등록 완료")
            return redirect("orders:order_list")
    else:
        form = WorkOrderForm()
        formset = WorkOrderLineFormSet()

    # 1) 수주목록 기본 조회 (최근 20건)
    sales_list = (
        CustomerOrderItem.objects
        .select_related("order", "product", "order__customer")
        .filter(order__delete_yn="N")
        .order_by("-order__order_date")[:20]
    )

    # ▼ 검색 파라미터
    customer_id = request.GET.get("customer", "").strip()
    q = request.GET.get("q", "").strip()

    # ▼ 고객사 드롭다운(활성만 표시하는 등 필요 시 필터 추가)
    customers = Vendor.objects.order_by("name")

    # ▼ 제품 검색 (고객사/품명/품번)
    product_qs = Product.objects.select_related("customer", "spec") \
        .filter(delete_yn="N", use_yn="Y")

    if customer_id:
        product_qs = product_qs.filter(customer_id=customer_id)

    if q:
        product_qs = product_qs.filter(
            Q(name__icontains=q) |
            Q(part_number__icontains=q) |
            Q(alias__icontains=q)
        )

    search_results = product_qs.order_by("customer__name", "name")[:50]

    context = {
        "form": form,
        "formset": formset,
        "sales_list": sales_list,              # (이미 있던 수주목록)
        "customers": customers,                # 👈 고객사 select
        "selected_customer": customer_id,
        "query": q,
        "search_results": search_results,      # 👈 검색 결과
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
            return redirect("orders:order_list")
    else:
        form = WorkOrderForm(instance=work_order)
        formset = WorkOrderLineFormSet(instance=work_order)

    context = {
        "form": form,
        "formset": formset,
        "work_order": work_order,
    }
    return render(request, "production/orders/order_form.html", context)


# 작업지시서 삭제
@transaction.atomic
def order_delete(request, pk):
    work_order = get_object_or_404(WorkOrder, pk=pk)

    if request.method == "POST":
        work_order.delete()
        messages.success(request, f"작업지시서 {work_order.work_lot} 삭제 완료")
        return redirect("orders:order_list")

    # GET 요청 시 확인 페이지 or 간단 확인 메시지
    context = {"work_order": work_order}
    return render(request, "production/orders/order_confirm_delete.html", context)

