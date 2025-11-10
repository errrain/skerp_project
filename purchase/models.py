# purchase/models.py
from __future__ import annotations

from decimal import Decimal
from django.conf import settings
from django.db import models, transaction
from django.db.models import Q, F, CheckConstraint, UniqueConstraint
from django.utils import timezone
from django.core.exceptions import ValidationError

# ── 외부 앱 참조 ─────────────────────────────────────────────────────────────
from injectionorder.models import InjectionOrder
from master.models import Warehouse
from partnerorder.models import PartnerShipmentGroup
from quality.inspections.models import IncomingInspectionDetail  # 실제 경로 확인 요망
from vendor.models import Vendor
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType


# =============================================================================
# LOT 카운터(동시성 안전한 일자별 연번 관리) — unmanaged 매핑
# =============================================================================
class ProductionLotCounter(models.Model):
    lot_type = models.TextField()
    lot_date = models.DateField()
    last_seq = models.IntegerField()

    class Meta:
        db_table = "production_lot_counter"
        managed = False
        constraints = [
            UniqueConstraint(fields=["lot_type", "lot_date"], name="uq_lotcounter_type_date"),
        ]

    @classmethod
    @transaction.atomic
    def next_seq(cls, lot_type: str, lot_date):
        from django.db import connection
        with connection.cursor() as cur:
            cur.execute(
                """
                INSERT INTO production_lot_counter (lot_type, lot_date, last_seq)
                VALUES (%s, %s, 0)
                ON CONFLICT DO NOTHING
                """,
                [lot_type, lot_date],
            )
        list(
            cls.objects.filter(lot_type=lot_type, lot_date=lot_date)
            .select_for_update()
            .values("lot_type")
        )
        cls.objects.filter(lot_type=lot_type, lot_date=lot_date).update(
            last_seq=F("last_seq") + 1
        )
        row = cls.objects.get(lot_type=lot_type, lot_date=lot_date)
        return row.last_seq


# =============================================================================
# 공통 베이스 전표 (입고/출고/반품)
# =============================================================================
class BaseDoc(models.Model):
    receipt_lot = models.CharField(max_length=20)
    date        = models.DateField()
    qty         = models.PositiveIntegerField(default=0)
    remark      = models.CharField(max_length=200, blank=True)

    created_by  = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="%(class)s_created",
    )
    created_at  = models.DateTimeField(auto_now_add=True)

    is_active   = models.BooleanField(default=True)
    is_deleted  = models.BooleanField(default=False)

    class Meta:
        abstract = True


# =============================================================================
# 사출: 입고 헤더/라인/이동 (기존 유지)
# =============================================================================
class InjectionReceipt(BaseDoc):
    order = models.ForeignKey(InjectionOrder, on_delete=models.PROTECT, related_name="receipts")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    shipment_group = models.ForeignKey(
        PartnerShipmentGroup, on_delete=models.PROTECT, related_name="injection_receipts"
    )
    is_used = models.BooleanField(default=False)
    used_at = models.DateTimeField(null=True, blank=True)
    order_lot_snapshot = models.CharField(max_length=40, blank=True)

    class Meta:
        db_table = "purchase_injectionreceipt"
        indexes = [
            models.Index(fields=["date", "receipt_lot"]),
            models.Index(fields=["is_active", "is_deleted"]),
            models.Index(fields=["is_used", "warehouse"]),
            models.Index(fields=["order"]),
            models.Index(fields=["shipment_group"]),
        ]
        constraints = [
            CheckConstraint(check=Q(qty__gt=0), name="injrec_qty_positive"),
            CheckConstraint(check=Q(is_used=True) | Q(used_at__isnull=True),
                            name="injrec_used_time_consistent"),
            UniqueConstraint(fields=["receipt_lot"], name="uniq_injectionreceipt_receipt_lot"),
        ]


class InjectionReceiptLine(models.Model):
    receipt = models.ForeignKey(
        "InjectionReceipt", on_delete=models.PROTECT, related_name="lines", verbose_name="입고 헤더"
    )
    detail  = models.OneToOneField(
        IncomingInspectionDetail, on_delete=models.PROTECT, related_name="receipt_line",
        verbose_name="검사 라인(PASS)",
    )
    qty     = models.PositiveIntegerField(verbose_name="입고 수량")
    created_at = models.DateTimeField(auto_now_add=True)

    sub_seq = models.PositiveIntegerField(null=False)
    sub_lot = models.CharField(max_length=32, unique=True, null=False)

    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT, related_name="inj_receipt_lines", null=True, blank=True
    )
    po_lot  = models.CharField(max_length=50, null=True, blank=True, db_index=True)
    po_part = models.CharField(max_length=20, null=True, blank=True, db_index=True)

    used_qty = models.PositiveIntegerField(default=0)
    USE_STATUS = (('미사용','미사용'), ('부분사용','부분사용'), ('사용완료','사용완료'))
    use_status = models.CharField(max_length=10, choices=USE_STATUS, default='미사용', db_index=True)

    class Meta:
        db_table = "purchase_injectionreceiptline"
        indexes = [
            models.Index(fields=["receipt"]),
            models.Index(fields=["detail"]),
            models.Index(fields=["warehouse"]),
            models.Index(fields=["po_lot", "po_part"]),
            models.Index(fields=["use_status"]),
        ]
        constraints = [
            UniqueConstraint(fields=["receipt", "sub_seq"], name="uniq_injrec_line_seq_per_receipt"),
            CheckConstraint(check=Q(qty__gt=0), name="injrec_line_qty_positive"),
            CheckConstraint(check=Q(used_qty__gte=0), name="inj_used_qty_ge_0"),
            CheckConstraint(check=Q(used_qty__lte=F('qty')), name="inj_used_qty_le_qty"),
        ]

    def _refresh_use_status(self):
        if (self.used_qty or 0) <= 0:
            self.use_status = '미사용'
        elif self.qty is not None and self.used_qty >= self.qty:
            self.use_status = '사용완료'
        else:
            self.use_status = '부분사용'

    def save(self, *args, **kwargs):
        if self.used_qty is None or self.used_qty < 0:
            self.used_qty = 0
        if self.qty is not None and self.used_qty > self.qty:
            self.used_qty = self.qty
        self._refresh_use_status()
        return super().save(*args, **kwargs)


class InjectionIssue(BaseDoc):
    receipt = models.ForeignKey("InjectionReceipt", on_delete=models.PROTECT, related_name="issues")
    from_warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="issue_from")
    to_warehouse   = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="issue_to")
    is_used_at_issue = models.BooleanField(default=False)

    receipt_line = models.ForeignKey(
        "InjectionReceiptLine", on_delete=models.PROTECT, related_name="issues",
        null=True, blank=True,
    )
    batch_id = models.UUIDField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "purchase_injectionissue"
        indexes = [
            models.Index(fields=["date", "receipt_lot"]),
            models.Index(fields=["from_warehouse", "to_warehouse"]),
            models.Index(fields=["receipt"]),
            models.Index(fields=["receipt_line"]),
            models.Index(fields=["batch_id"]),
        ]
        constraints = [
            CheckConstraint(check=Q(qty__gt=0), name="injissue_qty_positive"),
            CheckConstraint(check=~Q(from_warehouse=F("to_warehouse")), name="injissue_diff_wh"),
            UniqueConstraint(fields=["receipt_lot"], name="uniq_injectionissue_receipt_lot"),
        ]


# =============================================================================
# 통합(약품/비철/부자재)
# =============================================================================
CATEGORY_CHOICES = (("CHEM", "약품"), ("NF", "비철"), ("SUP", "부자재"))


class UnifiedReceipt(BaseDoc):
    category = models.CharField(max_length=8, choices=CATEGORY_CHOICES, db_index=True)
    vendor   = models.ForeignKey(Vendor, on_delete=models.PROTECT, related_name="unified_receipts")

    # 품목(GFK)
    item_ct  = models.ForeignKey(ContentType, on_delete=models.PROTECT)
    item_id  = models.PositiveBigIntegerField()
    item     = GenericForeignKey("item_ct", "item_id")

    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="unified_receipts")

    # 헤더 사용 집계(라인이 있으면 합산값, NF/SUP는 헤더만 사용)
    used_qty = models.DecimalField(max_digits=18, decimal_places=3, default=Decimal("0.000"))
    USE_STATUS = (('미사용','미사용'), ('부분사용','부분사용'), ('사용완료','사용완료'))
    use_status = models.CharField(max_length=10, choices=USE_STATUS, default='미사용', db_index=True)

    # 스냅샷
    item_name_snapshot = models.CharField(max_length=200)
    spec_snapshot      = models.CharField(max_length=200, blank=True)
    extra              = models.JSONField(default=dict, blank=True)

    # ★ 성적서 파일(NF/CHEM용, 선택)
    certificate_file = models.FileField(
        upload_to="purchase/receipts/certificates/%Y/%m/%d",
        null=True,
        blank=True,
    )

    # 구버전 호환 필드(완전 사용 여부)
    is_used = models.BooleanField(default=False)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "purchase_receipt"
        indexes = [
            models.Index(fields=["category", "date"]),
            models.Index(fields=["category", "warehouse"]),
            models.Index(fields=["category", "vendor"]),
            models.Index(fields=["item_ct", "item_id"]),
            models.Index(fields=["use_status"]),
        ]
        constraints = [
            CheckConstraint(check=Q(qty__gt=0), name="unirec_qty_positive"),
            CheckConstraint(check=Q(is_used=True) | Q(used_at__isnull=True),
                            name="unirec_used_time_consistent"),
            UniqueConstraint(fields=["receipt_lot"], name="uniq_unifiedreceipt_receipt_lot"),
            CheckConstraint(check=Q(used_qty__gte=0), name="unirec_used_qty_ge_0"),
        ]
        ordering = ["-date", "-id"]

    def _refresh_use_status(self):
        if (self.used_qty or Decimal("0")) <= 0:
            self.use_status = '미사용'
        elif self.qty is not None and self.used_qty >= Decimal(self.qty):
            self.use_status = '사용완료'
        else:
            self.use_status = '부분사용'

    def save(self, *args, **kwargs):
        if self.used_qty is None or self.used_qty < 0:
            self.used_qty = Decimal("0")
        # 헤더 qty는 정수형이지만 상태 판정엔 합리적 비교만 수행
        self._refresh_use_status()
        return super().save(*args, **kwargs)


class UnifiedReceiptLine(models.Model):
    """
    CHEM 전용 서브 LOT.
    - NF/SUP는 라인 미사용(헤더만 관리)
    """
    receipt = models.ForeignKey(
        "UnifiedReceipt", on_delete=models.PROTECT, related_name="lines", db_index=True
    )
    sub_seq = models.PositiveIntegerField(null=False)
    sub_lot = models.CharField(max_length=32, unique=True, null=False)

    # 수량/사용수량: Decimal(18,3)
    qty      = models.DecimalField(max_digits=18, decimal_places=3)
    used_qty = models.DecimalField(max_digits=18, decimal_places=3, default=Decimal("0.000"))

    USE_STATUS = (('미사용','미사용'), ('부분사용','부분사용'), ('사용완료','사용완료'))
    use_status = models.CharField(max_length=10, choices=USE_STATUS, default='미사용', db_index=True)

    # 라인별 현 위치(선택)
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT, related_name="unified_receipt_lines",
        null=True, blank=True
    )

    # ★ 서브 LOT 유효기간(약품 전용)
    expiry_date = models.DateField(null=True, blank=True)

    remark = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "purchase_unifiedreceiptline"
        indexes = [
            models.Index(fields=["receipt"]),
            models.Index(fields=["warehouse"]),
            models.Index(fields=["use_status"]),
        ]
        constraints = [
            UniqueConstraint(fields=["receipt", "sub_seq"], name="uniq_unirec_line_seq_per_receipt"),
            CheckConstraint(check=Q(qty__gt=0), name="unirec_line_qty_positive"),
            CheckConstraint(check=Q(used_qty__gte=0), name="unirec_line_used_ge_0"),
            CheckConstraint(check=Q(used_qty__lte=F('qty')), name="unirec_line_used_le_qty"),
        ]
        ordering = ["receipt_id", "sub_seq"]

    def _refresh_use_status(self):
        if (self.used_qty or Decimal("0")) <= 0:
            self.use_status = '미사용'
        elif self.qty is not None and self.used_qty >= self.qty:
            self.use_status = '사용완료'
        else:
            self.use_status = '부분사용'

    def save(self, *args, **kwargs):
        if self.used_qty is None or self.used_qty < 0:
            self.used_qty = Decimal("0")
        if self.qty is not None and self.used_qty > self.qty:
            self.used_qty = self.qty
        self._refresh_use_status()
        return super().save(*args, **kwargs)


class UnifiedIssue(BaseDoc):
    category  = models.CharField(max_length=8, choices=CATEGORY_CHOICES, db_index=True)
    receipt   = models.ForeignKey("UnifiedReceipt", on_delete=models.PROTECT, related_name="issues")
    from_warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="unified_issues_from")
    to_warehouse   = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="unified_issues_to")
    is_used_at_issue = models.BooleanField(default=False)

    class Meta:
        db_table = "purchase_issue"
        indexes = [
            models.Index(fields=["category", "date"]),
            models.Index(fields=["from_warehouse", "to_warehouse"]),
            models.Index(fields=["receipt"]),
        ]
        constraints = [
            CheckConstraint(check=Q(qty__gt=0), name="uniissue_qty_positive"),
            CheckConstraint(check=~Q(from_warehouse=F("to_warehouse")), name="uniissue_diff_wh"),
            UniqueConstraint(fields=["receipt_lot"], name="uniq_unifiedissue_receipt_lot"),
        ]
        ordering = ["-date", "-id"]


class UnifiedReturn(BaseDoc):
    category = models.CharField(max_length=8, choices=CATEGORY_CHOICES, db_index=True)
    receipt  = models.ForeignKey("UnifiedReceipt", on_delete=models.PROTECT, related_name="returns")
    from_warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="unified_returns_from")
    reason_code = models.CharField(max_length=40, blank=True)

    class Meta:
        db_table = "purchase_return"
        indexes = [
            models.Index(fields=["category", "date"]),
            models.Index(fields=["from_warehouse"]),
            models.Index(fields=["receipt"]),
        ]
        constraints = [
            CheckConstraint(check=Q(qty__gt=0), name="unireturn_qty_positive"),
            UniqueConstraint(fields=["receipt_lot"], name="uniq_unifiedreturn_receipt_lot"),
        ]
        ordering = ["-date", "-id"]


# =============================================================================
# 통합 발주(헤더/아이템) — 기존 유지
# =============================================================================
class UnifiedOrderStatus(models.TextChoices):
    NEW = "NEW", "발주"
    CNL = "CNL", "취소"


class UnifiedFlowStatus(models.TextChoices):
    NG  = "NG",  "미입고"
    PRT = "PRT", "부분입고"
    RCV = "RCV", "입고완료"


class UnifiedOrder(models.Model):
    category = models.CharField(max_length=8, choices=CATEGORY_CHOICES, db_index=True)
    vendor   = models.ForeignKey(Vendor, on_delete=models.PROTECT, related_name="unified_orders")

    order_lot   = models.CharField(max_length=20, unique=True)
    order_date  = models.DateField(db_index=True)
    due_date    = models.DateField(null=True, blank=True)

    order_status = models.CharField(max_length=3, choices=UnifiedOrderStatus.choices,
                                    default=UnifiedOrderStatus.NEW, db_index=True)
    flow_status  = models.CharField(max_length=3, choices=UnifiedFlowStatus.choices,
                                    default=UnifiedFlowStatus.NG, db_index=True)

    cancel_at    = models.DateTimeField(null=True, blank=True)
    cancel_by    = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="cancelled_unified_orders",
    )
    cancel_reason = models.CharField(max_length=200, blank=True)

    created_by   = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="unified_orders_created",
    )
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_by   = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="unified_orders_updated",
    )
    updated_at   = models.DateTimeField(auto_now=True)

    is_active    = models.BooleanField(default=True)
    is_deleted   = models.BooleanField(default=False)

    class Meta:
        db_table = "purchase_order"
        indexes = [
            models.Index(fields=["category", "order_date"]),
            models.Index(fields=["category", "vendor"]),
            models.Index(fields=["order_status"]),
            models.Index(fields=["flow_status"]),
        ]
        ordering = ["-order_date", "-id"]


class UnifiedOrderItem(models.Model):
    order = models.ForeignKey(UnifiedOrder, on_delete=models.CASCADE, related_name="items")
    item_ct = models.ForeignKey(ContentType, on_delete=models.PROTECT)
    item_id = models.PositiveBigIntegerField()
    item    = GenericForeignKey("item_ct", "item_id")

    qty         = models.PositiveIntegerField()
    unit_price  = models.DecimalField(max_digits=14, decimal_places=4, default=0)
    amount      = models.DecimalField(max_digits=16, decimal_places=4, default=0)

    expected_date = models.DateField(null=True, blank=True)
    item_name_snapshot = models.CharField(max_length=200)
    spec_snapshot      = models.CharField(max_length=200, blank=True)
    remark = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = "purchase_order_item"
        indexes = [
            models.Index(fields=["order"]),
            models.Index(fields=["item_ct", "item_id"]),
            models.Index(fields=["expected_date"]),
        ]
        constraints = [
            CheckConstraint(check=Q(qty__gt=0), name="uniorderitem_qty_positive"),
            CheckConstraint(check=Q(unit_price__gte=0), name="uniorderitem_unit_price_nonneg"),
            CheckConstraint(check=Q(amount__gte=0), name="uniorderitem_amount_nonneg"),
        ]
        ordering = ["id"]


# =============================================================================
# 사용 이력(레저)
# =============================================================================
class InjectionUsage(models.Model):
    class Action(models.TextChoices):
        CONSUME = "consume", "소비"
        RETURN  = "return",  "반납"
        ADJUST  = "adjust",  "조정"

    line = models.ForeignKey(
        "InjectionReceiptLine", on_delete=models.PROTECT, related_name="usages", db_index=True,
        verbose_name="사출 입고 라인",
    )
    action = models.CharField(max_length=10, choices=Action.choices, default=Action.CONSUME, db_index=True)
    qty_change = models.IntegerField(help_text="소비는 +, 반납은 -, 조정은 ± (0 불가)")
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="injection_usages",
        verbose_name="처리자",
    )
    ref_type = models.CharField(max_length=30, blank=True)
    ref_id   = models.CharField(max_length=64, blank=True)
    note     = models.CharField(max_length=200, blank=True)
    transaction_uid = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "purchase_injectionusage"
        ordering = ["-occurred_at", "-id"]
        indexes = [
            models.Index(fields=["line", "occurred_at"], name="injusage_line_time_idx"),
            models.Index(fields=["action"], name="injusage_action_idx"),
            models.Index(fields=["ref_type", "ref_id"], name="injusage_ref_idx"),
        ]
        constraints = [
            CheckConstraint(check=~Q(qty_change=0), name="injusage_qty_nonzero"),
            CheckConstraint(
                check=(
                    Q(action="consume", qty_change__gt=0) |
                    Q(action="return",  qty_change__lt=0) |
                    (Q(action="adjust") & ~Q(qty_change=0))
                ),
                name="injusage_sign_consistency",
            ),
        ]

    def clean(self):
        super().clean()
        if self.qty_change == 0:
            raise ValidationError("qty_change는 0일 수 없습니다.")
        if self.action == self.Action.CONSUME and self.qty_change <= 0:
            raise ValidationError("CONSUME는 양수여야 합니다.")
        if self.action == self.Action.RETURN and self.qty_change >= 0:
            raise ValidationError("RETURN는 음수여야 합니다.")


class UnifiedUsage(models.Model):
    """
    통합 사용 이력
    - CHEM: receipt(헤더) + line(필수)  → 서브 LOT 단위 사용 기록
    - NF/SUP: receipt(헤더)만          → 헤더 단위 사용 기록
    """
    class Action(models.TextChoices):
        CONSUME = "consume", "소비"
        RETURN  = "return",  "반납"
        ADJUST  = "adjust",  "조정"

    receipt = models.ForeignKey(
        "UnifiedReceipt", on_delete=models.PROTECT, related_name="usages",
        db_index=True, verbose_name="입고 전표(통합)",
    )
    # CHEM에서만 사용: 서브 LOT
    line = models.ForeignKey(
        "UnifiedReceiptLine", on_delete=models.PROTECT, related_name="usages",
        null=True, blank=True, db_index=True,
    )

    action = models.CharField(max_length=10, choices=Action.choices, default=Action.CONSUME, db_index=True)
    qty_change = models.DecimalField(max_digits=18, decimal_places=3,
                                     help_text="소비는 +, 반납은 -, 조정은 ± (0 불가)")
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="unified_usages",
        verbose_name="처리자",
    )
    ref_type = models.CharField(max_length=30, blank=True)
    ref_id   = models.CharField(max_length=64, blank=True)
    note     = models.CharField(max_length=200, blank=True)
    transaction_uid = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "purchase_unifiedusage"
        ordering = ["-occurred_at", "-id"]
        indexes = [
            models.Index(fields=["receipt", "occurred_at"], name="uniusage_receipt_time_idx"),
            models.Index(fields=["action"], name="uniusage_action_idx"),
            models.Index(fields=["ref_type", "ref_id"], name="uniusage_ref_idx"),
            models.Index(fields=["receipt", "line"]),
        ]
        constraints = [
            CheckConstraint(check=~Q(qty_change=0), name="uniusage_qty_nonzero"),
            CheckConstraint(
                check=(
                    Q(action="consume", qty_change__gt=0) |
                    Q(action="return",  qty_change__lt=0) |
                    (Q(action="adjust") & ~Q(qty_change=0))
                ),
                name="uniusage_sign_consistency",
            ),
        ]

    def clean(self):
        super().clean()
        if self.qty_change == 0:
            raise ValidationError("qty_change는 0일 수 없습니다.")
        if self.action == self.Action.CONSUME and self.qty_change <= 0:
            raise ValidationError("CONSUME는 양수여야 합니다.")
        if self.action == self.Action.RETURN and self.qty_change >= 0:
            raise ValidationError("RETURN는 음수여야 합니다.")

        # CHEM ↔ NF/SUP 라인 사용 규칙
        if self.receipt_id:
            cat = self.receipt.category
            if cat == "CHEM" and not self.line_id:
                raise ValidationError("CHEM 사용 이력은 반드시 서브 LOT(line)와 함께 기록해야 합니다.")
            if cat in ("NF", "SUP") and self.line_id:
                raise ValidationError("NF/SUP 사용 이력은 헤더 단위로만 기록해야 합니다(line 금지).")
