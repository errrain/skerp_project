from django.db import models, IntegrityError, transaction
from django.conf import settings
from django.utils import timezone
from django.core.exceptions import ValidationError
from datetime import datetime
from zoneinfo import ZoneInfo
import math

# -------------------------------
# Soft Delete Manager / QuerySet
# -------------------------------
class ActiveQuerySet(models.QuerySet):
    def alive(self):
        return self.filter(is_active=True, dlt_yn='N')

class ActiveManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(is_active=True, dlt_yn='N')


# -------------------------------
# Utility
# -------------------------------
def _ensure_aware(dt):
    """USE_TZ=True일 때 naive datetime이면 현재 타임존으로 aware 변환"""
    if not dt:
        return dt
    if getattr(settings, "USE_TZ", False) and timezone.is_naive(dt):
        return timezone.make_aware(dt, timezone.get_current_timezone())
    return dt

def _today_str():
    """LOT 생성을 위한 'YYYYMMDD' 문자열 반환"""
    if getattr(settings, "USE_TZ", False):
        now = timezone.now()
        if timezone.is_naive(now):
            now = timezone.make_aware(now, timezone.get_current_timezone())
        today = now.astimezone(timezone.get_current_timezone()).date()
    else:
        tzname = getattr(settings, "TIME_ZONE", "Asia/Seoul")
        today = datetime.now(ZoneInfo(tzname)).date()
    return today.strftime("%Y%m%d")


# -------------------------------
# WorkOrder
# -------------------------------
class WorkOrder(models.Model):
    """
    작업지시서 헤더 (EA 중심)
    - order_qty: 총 지시 수량(EA)
    - LOT 자동발급: JYYYYMMDD-### (ex: J20250905-001)
    - 상태: 대기/진행중/생산완료
    """
    # 소프트 삭제 공통 필드
    is_active = models.BooleanField("사용 여부", default=True, db_index=True)
    dlt_yn = models.CharField("삭제 여부", max_length=1,
                              choices=[('N', 'N'), ('Y', 'Y')],
                              default='N', db_index=True)

    STATUS_CHOICES = [
        ("대기", "대기"),
        ("진행중", "진행중"),
        ("생산완료", "생산완료"),
    ]

    # 기본 매니저: 살아있는 데이터만 / all_objects: 전체
    objects = ActiveManager()
    all_objects = models.Manager()

    work_lot = models.CharField("작업 LOT", max_length=20, unique=True, editable=False)

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

    # ---------- LOT 시퀀스/생성 ----------
    def _next_sequence_for(self, yyyymmdd: str) -> int:
        prefix = f"J{yyyymmdd}-"
        existing = WorkOrder.objects.filter(work_lot__startswith=prefix).count()
        return existing + 1

    def _generate_work_lot(self) -> str:
        ymd = _today_str()
        seq = self._next_sequence_for(ymd)
        return f"J{ymd}-{seq:03d}"

    # ---------- 저장 ----------
    def save(self, *args, **kwargs):
        self.planned_start = _ensure_aware(self.planned_start)
        self.planned_end = _ensure_aware(self.planned_end)
        self.actual_start = _ensure_aware(self.actual_start)
        self.actual_end = _ensure_aware(self.actual_end)

        if not self.work_lot:
            attempts = 5
            last_err = None
            for _ in range(attempts):
                try:
                    if not self.work_lot:
                        self.work_lot = self._generate_work_lot()
                    with transaction.atomic():
                        return super().save(*args, **kwargs)
                except IntegrityError as e:
                    last_err = e
                    self.work_lot = None
            raise last_err
        else:
            return super().save(*args, **kwargs)

    # ---------- 소프트 삭제/복구 ----------
    def soft_delete(self):
        type(self).all_objects.filter(pk=self.pk).update(is_active=False, dlt_yn='Y')
        self.lines.model.all_objects.filter(work_order=self).update(is_active=False, dlt_yn='Y')

    def restore(self):
        type(self).all_objects.filter(pk=self.pk).update(is_active=True, dlt_yn='N')
        self.lines.model.all_objects.filter(work_order=self).update(is_active=True, dlt_yn='N')


# -------------------------------
# WorkOrderLine
# -------------------------------
class WorkOrderLine(models.Model):
    """
    작업지시서 상세 (렉/행거 단위)
    - rack_capacity = product.product_per_rack
    - hanger_capacity = product.rack_per_hanger
    """
    work_order = models.ForeignKey(
        WorkOrder, on_delete=models.CASCADE, related_name="lines"
    )

    # 소프트 삭제 공통 필드
    is_active = models.BooleanField("사용 여부", default=True, db_index=True)
    dlt_yn = models.CharField("삭제 여부", max_length=1,
                              choices=[('N', 'N'), ('Y', 'Y')],
                              default='N', db_index=True)

    # 기본 매니저: 살아있는 데이터만 / all_objects: 전체
    objects = ActiveManager()
    all_objects = models.Manager()

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
            if self.rack_capacity in (None, 0):
                self.rack_capacity = getattr(product, "product_per_rack", None)
            if self.hanger_capacity in (None, 0):
                self.hanger_capacity = getattr(product, "rack_per_hanger", None)

        if not self.rack_capacity or not self.hanger_capacity:
            errors["rack_capacity"] = "rack_capacity와 hanger_capacity가 필요합니다."

        if self.work_order and self.rack_capacity and self.rack_count is not None:
            expected = self.expected_order_qty
            if expected > 0 and self.work_order.order_qty != expected:
                errors["work_order"] = (
                    f"지시수량({self.work_order.order_qty}) ≠ "
                    f"렉수({self.rack_count}) × 렉당수량({self.rack_capacity}) = {expected}"
                )

        if self.hanger_capacity and self.hanger_count is not None and self.rack_count is not None:
            if self.hanger_count * self.hanger_capacity < self.rack_count:
                need = self.required_hanger_count
                errors["hanger_count"] = (
                    f"행거 수({self.hanger_count}) 부족 → "
                    f"렉 {self.rack_count}개 수용하려면 최소 {need}행거 필요"
                )

        if errors:
            raise ValidationError(errors)

class WorkOrderInjectionUsage(models.Model):
    """
    작업 LOT 1건에 대해, 어떤 사출 입고 라인(InjectionReceiptLine)을
    몇 개(used_qty) 투입했는지 기록하는 테이블
    """
    workorder = models.ForeignKey(
        "WorkOrder",
        on_delete=models.CASCADE,
        related_name="injection_usages",
        verbose_name="작업지시",
    )
    line = models.ForeignKey(
        "purchase.InjectionReceiptLine",
        on_delete=models.PROTECT,
        related_name="workorder_usages",
        verbose_name="사출 입고 라인",
    )
    used_qty = models.PositiveIntegerField(default=0, verbose_name="투입 수량")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "production_workorder_injection_usage"
        unique_together = ("workorder", "line")   # 한 작업 LOT에 같은 라인 중복 방지

    def __str__(self):
        return f"{self.workorder.work_lot} ↔ {self.line.sub_lot} ({self.used_qty})"

#스페어파트 기본 모델
class SparePart(models.Model):
    """
    스페어파트 마스터
    - 기본정보: 품명 / 모델명 / 규격 / 비고
    - 재고요약: 현재 수량 / 최근 입고·출고 일시
    - 재고금액: 모든 입고금액 합계 (계산값, DB 컬럼 X)
    """
    # 소프트 삭제 공통 필드
    is_active = models.BooleanField("사용 여부", default=True, db_index=True)
    dlt_yn = models.CharField(
        "삭제 여부",
        max_length=1,
        choices=[("N", "N"), ("Y", "Y")],
        default="N",
        db_index=True,
    )

    objects = ActiveManager()
    all_objects = models.Manager()

    name = models.CharField("품명", max_length=100)
    model_name = models.CharField("모델명", max_length=100, blank=True)
    spec = models.CharField("규격", max_length=200, blank=True)
    remark = models.CharField("비고", max_length=100, blank=True)

    current_qty = models.IntegerField("현재 수량", default=0)
    last_in_at = models.DateTimeField("최근 입고일시", null=True, blank=True)
    last_out_at = models.DateTimeField("최근 사용일시", null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "스페어파트"
        verbose_name_plural = "스페어파트"

    def __str__(self):
        if self.model_name:
            return f"{self.name} ({self.model_name})"
        return self.name

    @property
    def total_receipt_amount(self):
        """
        재고금액 = 입고등록 이력의 금액 합계
        (출고와는 무관하게, 순수 입고총액)
        """
        agg = self.receipts.aggregate(
            total=models.Sum(
                models.F("amount") * models.F("quantity"),
                output_field=models.BigIntegerField(),
            )
        )
        return agg["total"] or 0

    def refresh_stock_summary(self):
        """
        입·출고 이력 기준으로 현재 수량 / 최근 입·출고 일시 재계산
        """
        in_agg = self.receipts.aggregate(
            total=models.Sum("quantity"),
            last=models.Max("received_at"),
        )
        out_agg = self.usages.aggregate(
            total=models.Sum("quantity"),
            last=models.Max("used_at"),
        )

        total_in = in_agg["total"] or 0
        total_out = out_agg["total"] or 0

        self.current_qty = total_in - total_out
        self.last_in_at = in_agg["last"]
        self.last_out_at = out_agg["last"]
        self.save(update_fields=["current_qty", "last_in_at", "last_out_at"])

#스페어파트 입고 이력 모델
class SparePartReceipt(models.Model):
    """
    스페어파트 입고 이력
    - 입고일시 / 거래처 / 수량 / 금액
    """
    spare_part = models.ForeignKey(
        SparePart,
        on_delete=models.CASCADE,
        related_name="receipts",
        verbose_name="스페어파트",
    )
    received_at = models.DateTimeField("입고일시")
    vendor = models.ForeignKey(
        "vendor.Vendor",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="spare_part_receipts",
        verbose_name="거래처",
    )
    quantity = models.PositiveIntegerField("입고 수량", default=0)
    amount = models.PositiveIntegerField("금액", default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-received_at", "-id"]
        verbose_name = "스페어파트 입고"
        verbose_name_plural = "스페어파트 입고"

    def __str__(self):
        return f"[입고] {self.spare_part.name} x {self.quantity} ({self.received_at})"


class SparePartUsage(models.Model):
    """
    스페어파트 사용(출고) 이력
    - 언제 / 어떤 공정(또는 설비) 때문에 / 얼마 사용했는지
    """
    spare_part = models.ForeignKey(
        SparePart,
        on_delete=models.CASCADE,
        related_name="usages",
        verbose_name="스페어파트",
    )
    used_at = models.DateTimeField("사용일시")

    process = models.ForeignKey(
        "process.Process",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="spare_part_usages",
        verbose_name="사용공정",
    )

    quantity = models.PositiveIntegerField("사용 수량", default=1)
    reason = models.CharField("사유", max_length=200, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-used_at", "-id"]
        verbose_name = "스페어파트 사용"
    verbose_name_plural = "스페어파트 사용"

    def __str__(self):
        return f"[사용] {self.spare_part.name} x {self.quantity} ({self.used_at})"


class ChemicalAddition(models.Model):
    """공정별 약품 투입 헤더 (공정/일자/근무조 단위)"""

    # 공통 플래그 (SparePart와 동일 패턴)
    is_active = models.BooleanField("사용 여부", default=True, db_index=True)
    dlt_yn = models.CharField(
        "삭제 여부",
        max_length=1,
        choices=[("N", "N"), ("Y", "Y")],
        default="N",
        db_index=True,
    )

    objects = ActiveManager()
    all_objects = models.Manager()

    process = models.ForeignKey(
        "process.Process",
        on_delete=models.PROTECT,
        related_name="chemical_additions",
        verbose_name="공정",
    )

    work_date = models.DateField("투입 일자")

    SHIFT_CHOICES = [
        ("DAY", "주간"),
        ("NIGHT", "야간"),
    ]
    shift = models.CharField(
        "근무조",
        max_length=10,
        choices=SHIFT_CHOICES,
        default="DAY",
    )

    remark = models.CharField("비고", max_length=200, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="등록자",
    )
    created_at = models.DateTimeField("등록일시", auto_now_add=True)

    class Meta:
        db_table = "production_chemical_addition"
        ordering = ["-work_date", "-id"]
        verbose_name = "약품 투입 헤더"
        verbose_name_plural = "약품 투입 헤더"
        unique_together = ("process", "work_date", "shift")

    def __str__(self):
        return f"{self.work_date} {self.get_shift_display()} - {self.process}"

class ChemicalAdditionLine(models.Model):
    """약품 투입 상세 (어떤 약품을 어떤 설비에 얼마나 넣었는지)"""

    addition = models.ForeignKey(
        ChemicalAddition,
        on_delete=models.CASCADE,
        related_name="lines",
        verbose_name="투입헤더",
    )

    chemical = models.ForeignKey(
        "chemical.Chemical",
        on_delete=models.PROTECT,
        related_name="chemical_addition_lines",
        verbose_name="약품",
    )

    equipment = models.ForeignKey(
        "equipment.Equipment",
        on_delete=models.PROTECT,
        related_name="chemical_addition_lines",
        verbose_name="투입설비",
    )

    quantity = models.DecimalField(
        "투입량",
        max_digits=10,
        decimal_places=3,  # 예: 600.000 ml 같은 값
    )
    unit = models.CharField("단위", max_length=10, default="ml")
    remark = models.CharField("비고", max_length=200, blank=True)

    created_at = models.DateTimeField("등록일시", auto_now_add=True)

    class Meta:
        db_table = "production_chemical_addition_line"
        ordering = ["addition_id", "id"]
        verbose_name = "약품 투입 상세"
        verbose_name_plural = "약품 투입 상세"

    def __str__(self):
        return f"{self.chemical} / {self.equipment} : {self.quantity}{self.unit}"