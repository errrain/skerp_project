# partnerorder/models.py
from django.db import models, transaction
from django.conf import settings
from django.utils import timezone
from django.core.validators import MinValueValidator

from injectionorder.models import InjectionOrder, FlowStatus
from injectionorder.models import InjectionOrderItem


class PartnerShipmentGroup(models.Model):
    """
    협력사 배송(부분출고) 1건 = 화면의 '배송상세' 블록 한 개
    - group_no: 주문 내 순번(1..N)
    - total_qty: 합계 수량 (라인이 있으면 라인 합계, 없으면 박스 합계 사용)
    """
    order = models.ForeignKey(
        InjectionOrder,
        on_delete=models.CASCADE,
        related_name="partner_shipments",
    )
    group_no = models.PositiveIntegerField(help_text="주문 내 순번(1..N)")
    ship_date = models.DateField()
    inject_date = models.DateField(null=True, blank=True)
    package_count = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        help_text="포장(박스/대차) 개수"
    )
    total_qty = models.PositiveIntegerField(default=0)
    note = models.CharField(max_length=200, blank=True)

    dlt_yn = models.CharField(max_length=1, choices=[("N", "N"), ("Y", "Y")], default="N")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        db_table = "partner_shipment_group"
        constraints = [
            models.UniqueConstraint(fields=["order", "group_no"], name="uq_psg_order_groupno"),
            models.CheckConstraint(check=models.Q(package_count__gte=1), name="chk_psg_pkgcnt_ge1"),
            models.CheckConstraint(check=models.Q(dlt_yn__in=["N", "Y"]), name="chk_psg_dlt_yn"),
        ]
        indexes = [models.Index(fields=["order"])]

    def __str__(self):
        return f"{self.order.order_lot} #{self.group_no}"

    def recalc_total(self) -> int:
        """
        합계 수량을 다시 계산.
        - 라인이 존재하면 라인 합계를 우선 사용
        - 라인이 없으면 기존 박스 합계를 사용(하위 호환)
        """
        line_sum = self.items.filter(dlt_yn="N").aggregate(s=models.Sum("qty"))["s"] or 0
        if line_sum and line_sum > 0:
            tot = line_sum
        else:
            tot = self.boxes.filter(dlt_yn="N").aggregate(s=models.Sum("qty"))["s"] or 0

        self.total_qty = tot
        self.save(update_fields=["total_qty", "updated_at"])
        return tot


class PartnerShipmentBox(models.Model):
    """
    포장(박스/대차) 단위 수량 — 기존 구조 유지(하위 호환)
    새 라인(PartnerShipmentLine)이 도입되었더라도, 과거 데이터/화면과의 호환을 위해 존치.
    """
    group = models.ForeignKey(
        PartnerShipmentGroup, on_delete=models.CASCADE, related_name="boxes"
    )
    box_no = models.PositiveIntegerField()
    qty = models.PositiveIntegerField(validators=[MinValueValidator(1)])

    dlt_yn = models.CharField(max_length=1, choices=[("N", "N"), ("Y", "Y")], default="N")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "partner_shipment_box"
        constraints = [
            models.UniqueConstraint(fields=["group", "box_no"], name="uq_psb_group_boxno"),
            models.CheckConstraint(check=models.Q(qty__gte=1), name="chk_psb_qty_ge1"),
            models.CheckConstraint(check=models.Q(dlt_yn__in=["N", "Y"]), name="chk_psb_dlt_yn"),
        ]
        indexes = [models.Index(fields=["group"])]

    def __str__(self):
        return f"G{self.group.group_no}-{self.box_no} ({self.qty})"


class PartnerShipmentLine(models.Model):
    """
    배송상세(그룹)의 하위 라인. “2-1 : 150” 형태의 표시를 위해 sub_seq로 순번 관리.
    - shipment: 상위 배송상세(그룹)
    - sub_seq : 그룹 내 하위 순번(1..N) → 화면 표기: "{group_no}-{sub_seq} : qty"
    - qty     : 수량
    - production_date: 생산일(있으면 저장)
    """
    shipment = models.ForeignKey(
        PartnerShipmentGroup,
        on_delete=models.CASCADE,
        related_name="items",           # ⚠ views에서 prefetch_related("partner_shipments__items")로 사용
        verbose_name="배송상세(그룹)",
    )
    sub_seq = models.PositiveIntegerField(verbose_name="하위 순번")
    qty     = models.PositiveIntegerField(verbose_name="수량")
    production_date = models.DateField(null=True, blank=True, verbose_name="생산일")
    remark  = models.CharField(max_length=200, blank=True)

    dlt_yn = models.CharField(max_length=1, default="N")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "partner_shipment_line"
        verbose_name = "배송 라인"
        verbose_name_plural = "배송 라인"
        unique_together = [("shipment", "sub_seq")]
        ordering = ["id"]
        indexes = [models.Index(fields=["shipment"])]

    def __str__(self):
        return f"ShipLine(shipment={self.shipment_id}, sub={self.sub_seq}, qty={self.qty})"

    @property
    def label(self) -> str:
        """화면 표기용 라벨: '그룹-하위순번' (예: '2-1')"""
        try:
            return f"{self.shipment.group_no}-{self.sub_seq}"
        except Exception:
            return f"{self.sub_seq}"


# ---------- 집계 & 상태 전이 도우미 ----------
def _ordered_sum(order: InjectionOrder) -> int:
    return (
        InjectionOrderItem.objects
        .filter(order=order, dlt_yn="N")
        .aggregate(s=models.Sum("quantity"))["s"]
        or 0
    )


def _shipped_sum(order: InjectionOrder) -> int:
    """
    주문 기준 출고(배송) 합계.
    - 라인(PartnerShipmentLine)이 있으면 라인 합계를 우선 사용
    - 라인이 없으면 박스(PartnerShipmentBox) 합계를 사용(하위 호환)
    """
    line_sum = (
        PartnerShipmentLine.objects.filter(
            shipment__order=order,
            dlt_yn="N",
            shipment__dlt_yn="N",
        ).aggregate(s=models.Sum("qty"))["s"] or 0
    )
    if line_sum and line_sum > 0:
        return line_sum

    return (
        PartnerShipmentBox.objects.filter(
            group__order=order, dlt_yn="N", group__dlt_yn="N"
        ).aggregate(s=models.Sum("qty"))["s"]
        or 0
    )


@transaction.atomic
def recalc_order_shipping_and_flow(order: InjectionOrder):
    """
    박스/라인 기준 합계를 다시 계산하고 주문 진행상태를 안전하게 갱신.
    - NG  : 전혀 출고(배송) 없음
    - PRT : 부분 출고(배송)
    - RCV : 주문 수량 이상 출고(배송) 완료
    """
    ordered = _ordered_sum(order)
    shipped = _shipped_sum(order)

    if shipped <= 0:
        new_flow = FlowStatus.NG
    elif shipped < ordered:
        new_flow = FlowStatus.PRT
    else:
        new_flow = FlowStatus.RCV

    update_fields = []
    if order.flow_status != new_flow:
        order.flow_status = new_flow
        update_fields.append("flow_status")

    # 최초 배송이면 shipping_registered_at 기록(필드가 존재할 때만)
    if shipped > 0 and hasattr(order, "shipping_registered_at") and not order.shipping_registered_at:
        order.shipping_registered_at = timezone.now()
        update_fields.append("shipping_registered_at")

    if update_fields:
        update_fields.append("updated_at")
        order.save(update_fields=update_fields)

    return {
        "ordered": ordered,
        "shipped": shipped,
        "remain": max(0, ordered - shipped),
        "flow": new_flow,
    }
