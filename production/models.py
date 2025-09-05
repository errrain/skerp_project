from django.db import models, transaction
from django.conf import settings
from django.utils import timezone
from django.core.exceptions import ValidationError
import math


class WorkOrder(models.Model):
    """
    작업지시서 헤더 (EA 중심)
    - order_qty: 총 지시 수량(EA)
    - LOT 자동발급: JYYYYMMDD-#### (ex: J20250905-0001)
    - 상태: 대기/진행중/생산완료
    """

    STATUS_CHOICES = [
        ("대기", "대기"),
        ("진행중", "진행중"),
        ("생산완료", "생산완료"),
    ]

    work_lot = models.CharField("작업 LOT", max_length=20, unique=True, editable=False)

    # 제품(Product) 기준으로 수정
    product = models.ForeignKey(
        "product.Product", on_delete=models.PROTECT, related_name="work_orders"
    )
    customer = models.ForeignKey(
        "vendor.Vendor", on_delete=models.PROTECT, related_name="work_orders"
    )

    order_qty = models.PositiveIntegerField("지시 수량(EA)")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="대기")

    planned_start = models.DateTimeField("계획 시작", null=True, blank=True)
    planned_end = models.DateTimeField("계획 종료", null=True, blank=True)
    actual_start = models.DateTimeField("실 시작", null=True, blank=True)
    actual_end = models.DateTimeField("실 종료", null=True, blank=True)

    remark = models.CharField("비고", max_length=200, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "작업지시서"
        verbose_name_plural = "작업지시서"

    def __str__(self):
        return f"{self.work_lot} - {self.product.name} ({self.order_qty}EA)"

    def _generate_work_lot(self) -> str:
        today = timezone.localdate().strftime("%Y%m%d")
        prefix = f"J{today}-"
        with transaction.atomic():
            last = (
                WorkOrder.objects
                .select_for_update()
                .filter(work_lot__startswith=prefix)
                .order_by("-work_lot")
                .first()
            )
            last_seq = int(last.work_lot.split("-")[-1]) if last else 0
            return f"{prefix}{last_seq + 1:04d}"

    def save(self, *args, **kwargs):
        if not self.work_lot:
            self.work_lot = self._generate_work_lot()
        super().save(*args, **kwargs)


class WorkOrderLine(models.Model):
    """
    작업지시서 상세 (렉/행거 단위)
    - rack_capacity = product.product_per_rack
    - hanger_capacity = product.rack_per_hanger
    - 유효성:
        order_qty == rack_count * rack_capacity
        hanger_count * hanger_capacity >= rack_count
    """

    work_order = models.ForeignKey(
        WorkOrder, on_delete=models.CASCADE, related_name="lines"
    )

    rack_capacity = models.PositiveIntegerField("1렉당 수용량(EA)", null=True, blank=True)
    rack_count = models.PositiveIntegerField("렉 수", default=0)

    hanger_capacity = models.PositiveIntegerField("1행거당 렉 수", null=True, blank=True)
    hanger_count = models.PositiveIntegerField("행거 수", default=0)

    sequence = models.PositiveIntegerField("작업 순서", default=1)
    remark = models.CharField("비고", max_length=200, blank=True)

    class Meta:
        ordering = ["work_order", "sequence"]
        verbose_name = "작업지시서 상세"
        verbose_name_plural = "작업지시서 상세"

    def __str__(self):
        return f"{self.work_order.work_lot} - seq{self.sequence} | {self.rack_count}R / {self.hanger_count}H"

    @property
    def expected_order_qty(self) -> int:
        if not self.rack_capacity or not self.rack_count:
            return 0
        return self.rack_count * self.rack_capacity

    @property
    def required_hanger_count(self) -> int:
        if not self.hanger_capacity:
            return 0
        return math.ceil((self.rack_count or 0) / self.hanger_capacity)

    def clean(self):
        errors = {}

        product = getattr(self.work_order, "product", None)
        if product:
            # product 모델 값 가져와 기본 세팅
            if self.rack_capacity in (None, 0):
                self.rack_capacity = getattr(product, "product_per_rack", None)
            if self.hanger_capacity in (None, 0):
                self.hanger_capacity = getattr(product, "rack_per_hanger", None)

        # 필수값 확인
        if not self.rack_capacity or not self.hanger_capacity:
            errors["rack_capacity"] = "rack_capacity와 hanger_capacity가 필요합니다."

        # 수량 유효성 검사
        if self.work_order and self.rack_capacity and self.rack_count is not None:
            expected = self.expected_order_qty
            if expected > 0 and self.work_order.order_qty != expected:
                errors["work_order"] = (
                    f"지시수량({self.work_order.order_qty}) ≠ "
                    f"렉수({self.rack_count}) × 렉당수량({self.rack_capacity}) = {expected}"
                )

        # 행거 수용성 검사
        if self.hanger_capacity and self.hanger_count is not None and self.rack_count is not None:
            if self.hanger_count * self.hanger_capacity < self.rack_count:
                need = self.required_hanger_count
                errors["hanger_count"] = (
                    f"행거 수({self.hanger_count}) 부족 → "
                    f"렉 {self.rack_count}개 수용하려면 최소 {need}행거 필요"
                )

        if errors:
            raise ValidationError(errors)
