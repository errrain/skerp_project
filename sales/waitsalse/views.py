# sales/waitsalse/views.py
from types import SimpleNamespace

from django.db.models import Sum, Count, Case, When, IntegerField
from django.shortcuts import render


from quality.inspections.models import FinishedBox  # ✅ 최종 경로


def product_stock_list(request):
    # 1) 기본 queryset : 출하 안 됐고 삭제 안 된 BOX = 현재 재고(LOT 단위)
    qs = (
        FinishedBox.objects
        .filter(shipped=False, dlt_yn="N")
        .select_related("product")
    )

    # 2) 필터 값
    customer = (request.GET.get("customer") or "").strip()
    part     = (request.GET.get("part") or "").strip()
    name     = (request.GET.get("name") or "").strip()
    status   = (request.GET.get("status") or "").strip()  # FULL / SHORT

    # 3) 필터링
    if part:
        qs = qs.filter(product__part_number__icontains=part)
    if name:
        qs = qs.filter(product__name__icontains=name)
    if status:
        qs = qs.filter(status=status)
    if customer:
        # Product에 customer FK가 있으면 사용
        qs = qs.filter(product__customer__name__icontains=customer)

    # 4) 정렬 (원하는 순서대로)
    qs = qs.order_by("product__part_number", "lot_no")

    # 5) 템플릿에서 쓰기 쉽게 변환 (원하면 그냥 qs 넘겨도 됨)
    items = [
        SimpleNamespace(
            lot_no=fb.lot_no,
            part_number=fb.product.part_number if fb.product else "",
            name=fb.product.name if fb.product else "",
            qty=fb.qty,
            box_size=fb.box_size,
            status=fb.status,
            shipped=fb.shipped,
        )
        for fb in qs
    ]

    context = {
        "items": items,
        "filter": {
            "customer": customer,
            "part": part,
            "name": name,
            "status": status,
        },
    }
    return render(request, "waitsales/waitsales_list.html", context)
