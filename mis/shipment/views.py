# mis/shipment/views.py
from django.shortcuts import render
from django.utils.dateparse import parse_date
from django.db.models import Sum
from sales.models import SalesShipment


def shipment_summary(request):
    ship_date_from = (request.GET.get("ship_date_from") or "").strip()
    ship_date_to = (request.GET.get("ship_date_to") or "").strip()
    customer = (request.GET.get("customer") or "").strip()
    program = (request.GET.get("program") or "").strip()
    product_name = (request.GET.get("product_name") or "").strip()

    qs = (
        SalesShipment.objects
        .select_related("customer")
        .filter(delete_yn="N")
    )

    if ship_date_from:
        d_from = parse_date(ship_date_from)
        if d_from:
            qs = qs.filter(ship_date__gte=d_from)
    if ship_date_to:
        d_to = parse_date(ship_date_to)
        if d_to:
            qs = qs.filter(ship_date__lte=d_to)

    if customer:
        qs = qs.filter(customer__name__icontains=customer)
    if program:
        qs = qs.filter(program__icontains=program)
    if product_name:
        qs = qs.filter(product_name__icontains=product_name)

    daily_stats = (
        qs.values("ship_date")
          .annotate(total_qty=Sum("total_qty"))
          .order_by("ship_date")
    )

    customer_stats = (
        qs.values("customer__name")
          .annotate(total_qty=Sum("total_qty"))
          .order_by("customer__name")
    )

    context = {
        "ship_date_from": ship_date_from,
        "ship_date_to": ship_date_to,
        "customer": customer,
        "program": program,
        "product_name": product_name,
        "daily_stats": daily_stats,
        "customer_stats": customer_stats,
    }
    return render(request, "shipment/shipment_summary.html", context)
