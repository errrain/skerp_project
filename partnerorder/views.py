# partnerorder/views.py
from datetime import datetime
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Prefetch, Sum, Q
from django.http import HttpResponse, HttpResponseForbidden
import csv, io, base64, qrcode

# 추가 import
from django.views.generic import ListView
from django.db import models  # <- models.Max 사용 대비
from injectionorder.models import FlowStatus  # 선택박스에 필요

from injectionorder.models import InjectionOrder, OrderStatus
from injectionorder.models import InjectionOrderItem
from .models import (
    PartnerShipmentGroup,
    PartnerShipmentBox,
    recalc_order_shipping_and_flow,
)

def _parse_date(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date() if s else None
    except Exception:
        return None


@login_required
def order_detail(request, order_id):
    order = get_object_or_404(
        InjectionOrder.objects.select_related("vendor"),
        id=order_id, dlt_yn="N"
    )

    # 벤더 스코프(외부 사용자라면 자기 것만)
    u = request.user
    if hasattr(u, "is_internal") and not u.is_internal:
        if getattr(u, "vendor_id", None) != order.vendor_id:
            return HttpResponseForbidden("권한 없음")

    # 헤더 합계(살아있는 라인만)
    ordered_sum = (
        InjectionOrderItem.objects
        .filter(order=order, dlt_yn="N")
        .aggregate(s=Sum("quantity"))["s"] or 0
    )
    # 배송 합계(살아있는 박스 + 살아있는 그룹만)
    shipped_sum = (
        PartnerShipmentBox.objects
        .filter(group__order=order, dlt_yn="N", group__dlt_yn="N")
        .aggregate(s=Sum("qty"))["s"] or 0
    )
    remain = max(0, ordered_sum - shipped_sum)

    # ✅ 배송상세: 소프트 삭제 포함(기록 보존), 취소건이 뒤로 가지 않게 dlt_yn → group_no 순 정렬
    groups = (
        PartnerShipmentGroup.objects
        .filter(order=order)                         # dlt_yn 조건 제거
        .prefetch_related("boxes")                   # 박스도 같이(삭제여부 그대로 노출)
        .order_by("dlt_yn", "group_no", "id")
    )

    # 대표 품명(표시용)
    first_item = (
        InjectionOrderItem.objects
        .select_related("injection")
        .filter(order=order, dlt_yn="N")
        .order_by("id").first()
    )
    first_name = first_item.injection.name if first_item else "-"

    return render(
        request, "partnerorder/order_detail.html",
        {
            "order": order,
            "ordered_sum": ordered_sum,
            "shipped_sum": shipped_sum,
            "remain": remain,
            "groups": groups,
            "first_product_name": first_name,
        },
    )
@login_required
@transaction.atomic
def shipment_add(request, order_id):
    if request.method != "POST":
        return HttpResponseForbidden("POST only")

    order = get_object_or_404(InjectionOrder, id=order_id, dlt_yn="N")

    # 상태/권한 체크
    if order.order_status != OrderStatus.NEW:
        return HttpResponseForbidden("취소된 발주는 등록 불가")

    u = request.user
    if hasattr(u, "is_internal") and not u.is_internal:
        if getattr(u, "vendor_id", None) != order.vendor_id:
            return HttpResponseForbidden("권한 없음")

    ship_date = _parse_date(request.POST.get("ship_date"))
    inject_date = _parse_date(request.POST.get("inject_date"))
    pkg_cnt = int(request.POST.get("package_count") or 0)

    # 박스 수량 수집: name="box_qty_1" .. "box_qty_N"
    box_qtys = []
    for i in range(1, pkg_cnt + 1):
        v = request.POST.get(f"box_qty_{i}")
        if v is None or not str(v).isdigit():
            continue
        q = int(v)
        if q > 0:
            box_qtys.append(q)

    if not ship_date or pkg_cnt < 1 or len(box_qtys) != pkg_cnt:
        return HttpResponseForbidden("입력값 오류")

    # 잔량 검증
    ordered_sum = (
        InjectionOrderItem.objects.filter(order=order, dlt_yn="N").aggregate(s=Sum("quantity"))["s"]
        or 0
    )
    shipped_sum = (
        PartnerShipmentBox.objects.filter(group__order=order, dlt_yn="N", group__dlt_yn="N")
        .aggregate(s=Sum("qty"))["s"]
        or 0
    )
    add_sum = sum(box_qtys)
    if shipped_sum + add_sum > ordered_sum:
        return HttpResponseForbidden(f"입력 합계가 발주수량을 초과(잔량 {ordered_sum - shipped_sum})")

    # 순번
    next_no = (
        PartnerShipmentGroup.objects.filter(order=order).aggregate(m=models.Max("group_no"))["m"]
        or 0
    ) + 1

    # 생성
    grp = PartnerShipmentGroup.objects.create(
        order=order,
        group_no=next_no,
        ship_date=ship_date,
        inject_date=inject_date,
        package_count=pkg_cnt,
        created_by=request.user,
        updated_by=request.user,
    )
    for idx, qty in enumerate(box_qtys, start=1):
        PartnerShipmentBox.objects.create(group=grp, box_no=idx, qty=qty)

    grp.recalc_total()
    recalc_order_shipping_and_flow(order)

    return redirect("partner:order_detail", order_id=order.id)


@login_required
@transaction.atomic
def shipment_delete(request, group_id):
    if request.method != "POST":
        return HttpResponseForbidden("POST only")

    grp = get_object_or_404(PartnerShipmentGroup, id=group_id, dlt_yn="N")
    order = grp.order

    # 간단 권한
    u = request.user
    if hasattr(u, "is_internal") and not u.is_internal:
        if getattr(u, "vendor_id", None) != order.vendor_id:
            return HttpResponseForbidden("권한 없음")

    grp.dlt_yn = "Y"
    grp.save(update_fields=["dlt_yn", "updated_at"])
    grp.boxes.update(dlt_yn="Y")
    recalc_order_shipping_and_flow(order)

    return redirect("partner:order_detail", order_id=order.id)


@login_required
def shipment_qr(request, group_id):
    """배송상세(그룹) 내 박스별 QR 프린트."""
    grp = get_object_or_404(
        PartnerShipmentGroup.objects
        .select_related("order", "order__vendor")
        .prefetch_related("boxes"),
        id=group_id
    )

    # 대표 품명(요청 파라미터 우선, 없으면 라인 첫 품명)
    item_name = (request.GET.get("item_name") or "").strip()
    if not item_name:
        first_item = (
            InjectionOrderItem.objects
            .select_related("injection")
            .filter(order=grp.order, dlt_yn="N")
            .order_by("id")
            .first()
        )
        item_name = first_item.injection.name if first_item else "-"

    cards = []
    for b in grp.boxes.filter(dlt_yn="N").order_by("box_no"):
        payload = {
            "order_lot": grp.order.order_lot,
            "vendor": grp.order.vendor.name if grp.order.vendor else "",
            "item": item_name,
            "group": grp.group_no,
            "box": b.box_no,
            "qty": b.qty,
            "ship_date": grp.ship_date.strftime("%Y-%m-%d") if grp.ship_date else "",
            "inject_date": grp.inject_date.strftime("%Y-%m-%d") if grp.inject_date else "",
        }
        img = qrcode.make(payload)  # QR 내용: 위 payload 통째로
        buf = io.BytesIO()
        img.save(buf, format="PNG")

        cards.append({
            "o": grp.order,          # 주문(LOT/발주처/발주일/입고예정일 등 템플릿에서 사용)
            "item_name": item_name,  # 품명
            "ship_date": payload["ship_date"],
            "inject_date": payload["inject_date"],
            "group_no": grp.group_no,
            "box_no": b.box_no,
            "qty": b.qty,
            "qr_b64": base64.b64encode(buf.getvalue()).decode(),
        })

    return render(request, "partnerorder/print_qr.html", {
        "group": grp,
        "cards": cards,
    })

class OrderListView(ListView):
    template_name = "partnerorder/order_list.html"
    context_object_name = "object_list"
    paginate_by = 20

    def _parse_date(self, s):
        try:
            from datetime import datetime
            return datetime.strptime(s, "%Y-%m-%d").date() if s else None
        except Exception:
            return None

    def get_queryset(self):
        qs = (InjectionOrder.objects
              .select_related("vendor")
              .filter(dlt_yn="N", use_yn="Y")  # ✅ 헤더: 삭제/미사용 제외
              .filter(items__dlt_yn="N")  # ✅ 라인: 살아있는 라인 1건 이상 조건
              .order_by("-order_date", "-id")
              .distinct())

        g = self.request.GET
        d1 = self._parse_date(g.get("from"))
        d2 = self._parse_date(g.get("to"))
        e1 = self._parse_date(g.get("expected_from"))
        e2 = self._parse_date(g.get("expected_to"))
        vendor = (g.get("vendor") or "").strip()
        product = (g.get("product") or "").strip()
        order_status = (g.get("order_status") or "").strip()
        flow_status = (g.get("flow_status") or "").strip()

        if d1: qs = qs.filter(order_date__gte=d1)
        if d2: qs = qs.filter(order_date__lte=d2)
        # 입고예정일(라인 기반)
        if e1: qs = qs.filter(items__dlt_yn="N", items__expected_date__gte=e1)
        if e2: qs = qs.filter(items__dlt_yn="N", items__expected_date__lte=e2)

        if vendor: qs = qs.filter(vendor__name__icontains=vendor)
        if product:
            qs = qs.filter(items__dlt_yn="N", items__injection__name__icontains=product)
        if order_status: qs = qs.filter(order_status=order_status)
        if flow_status: qs = qs.filter(flow_status=flow_status)

        qs = qs.distinct()

        # 라인(살아있는 것만) 프리패치 + 대표품명/합계 표시용
        pre = Prefetch(
            lookup="items",  # ← 모델의 related_name에 맞춰 변경
            queryset=(InjectionOrderItem.objects.filter(dlt_yn="N").select_related("injection")),
            to_attr="alive_items",
        )
        qs = qs.prefetch_related(pre)

        # 템플릿에서 쓰는 qty_sum 필드를 파이썬에서 계산해 붙임
        for o in qs:
            o.qty_sum = sum(i.quantity for i in getattr(o, "alive_items", []))
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["order_status_choices"] = OrderStatus.choices
        ctx["flow_status_choices"] = FlowStatus.choices
        q = self.request.GET.copy()
        q.pop("page", None)
        ctx["querystring"] = q.urlencode()
        return ctx

@login_required
def order_export(request):
    # 목록과 동일한 필터를 재사용
    view = OrderListView()
    view.request = request
    orders = view.get_queryset()

    # 한글 깨짐 방지: utf-8-sig
    resp = HttpResponse(content_type="text/csv; charset=utf-8-sig")
    resp["Content-Disposition"] = 'attachment; filename="partner_orders.csv"'
    writer = csv.writer(resp)
    writer.writerow(["발주LOT","발주처","발주일","품명(대표)","수량합",
                     "입고예정일","발주상태","진행상태","취소일시","취소자"])

    for o in orders:
        item_name = "-"
        if getattr(o, "alive_items", None):
            first = o.alive_items[0] if o.alive_items else None
            item_name = first.injection.name if first else "-"
        writer.writerow([
            o.order_lot,
            o.vendor.name if o.vendor else "-",
            o.order_date.strftime("%Y-%m-%d") if o.order_date else "-",
            item_name,
            getattr(o, "qty_sum", 0),
            o.due_date.strftime("%Y-%m-%d") if getattr(o, "due_date", None) else "-",
            o.get_order_status_display(),
            o.get_flow_status_display(),
            o.cancel_at.strftime("%Y-%m-%d %H:%M") if getattr(o, "cancel_at", None) else "-",
            (getattr(o.cancel_by, "full_name", None) or
             getattr(o.cancel_by, "username", None) or "-") if getattr(o, "cancel_by", None) else "-"
        ])
    return resp
