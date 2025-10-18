# purchase/models.py
from __future__ import annotations

from django.conf import settings
from django.db import models, transaction
from django.db.models import Q, F, CheckConstraint, UniqueConstraint

# ── 외부 앱 참조 ─────────────────────────────────────────────────────────────
from injectionorder.models import InjectionOrder
from master.models import Warehouse
from partnerorder.models import PartnerShipmentGroup
from quality.inspections.models import IncomingInspectionDetail  # 프로젝트 실제 경로 확인 요망
from vendor.models import Vendor

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType



# =============================================================================
# LOT 카운터(동시성 안전한 일자별 연번 관리)
#   - 실제 DB 테이블: production_lot_counter (PK: lot_type, lot_date)
#   - 입고 LOT 생성 시 (lot_type='INJ_RCPT', lot_date=입고일)로 사용
#   - unmanaged 매핑: Django가 테이블을 만들지 않도록 반드시 managed=False
# =============================================================================
class ProductionLotCounter(models.Model):
    lot_type = models.TextField()
    lot_date = models.DateField()
    last_seq = models.IntegerField()

    class Meta:
        db_table = "production_lot_counter"
        managed = False  # ★ 반드시 False (CreateModel 방지)
        # 아래 제약은 모델 표현용일 뿐, managed=False라 마이그레이션에는 반영되지 않습니다.
        constraints = [
            UniqueConstraint(fields=["lot_type", "lot_date"], name="uq_lotcounter_type_date"),
        ]

    @classmethod
    @transaction.atomic
    def next_seq(cls, lot_type: str, lot_date):
        """
        (lot_type, lot_date) 행을 잠그고 last_seq를 +1 후 값 반환.
        - create/save 대신 raw SQL/UPDATE를 사용해 복합키 + unmanaged에서도 안전.
        - 동시성: SELECT FOR UPDATE + UPDATE + 재조회.
        """
        from django.db import connection

        # 1) 없다면 초기 행 삽입 (ON CONFLICT DO NOTHING)
        with connection.cursor() as cur:
            cur.execute(
                """
                INSERT INTO production_lot_counter (lot_type, lot_date, last_seq)
                VALUES (%s, %s, 0)
                ON CONFLICT DO NOTHING
                """,
                [lot_type, lot_date],
            )

        # 2) 잠금 획득
        list(
            cls.objects.filter(lot_type=lot_type, lot_date=lot_date)
            .select_for_update()
            .values("lot_type")
        )

        # 3) +1 업데이트
        cls.objects.filter(lot_type=lot_type, lot_date=lot_date).update(
            last_seq=F("last_seq") + 1
        )

        # 4) 증가된 값 조회
        row = cls.objects.get(lot_type=lot_type, lot_date=lot_date)
        return row.last_seq


# =============================================================================
# 공통 베이스 전표 (입고/출고/반품)
#   - 사출/통합 전표에서 공통 사용
# =============================================================================
class BaseDoc(models.Model):
    # 전표 LOT (입고: INYYYYMMDDNNN, 출고: ISYYYYMMDDNNN 등)
    receipt_lot = models.CharField(max_length=20, db_index=True)
    date        = models.DateField()
    qty         = models.PositiveIntegerField(default=0)
    remark      = models.CharField(max_length=200, blank=True)

    created_by  = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="%(class)s_created",
    )
    created_at  = models.DateTimeField(auto_now_add=True)

    # 운영 플래그
    is_active   = models.BooleanField(default=True)
    is_deleted  = models.BooleanField(default=False)

    class Meta:
        abstract = True


# =============================================================================
# 사출: 입고 헤더
#   - 헤더(InjectionReceipt)는 "배송그룹" 단위 LOT 1건을 재사용
#   - 라인(InjectionReceiptLine)은 그룹 내 각 배송 라인별 서브 LOT 1건
#   - 1차(완화): shipment_group NULL 허용 → 백필 후 NOT NULL로 격상
# =============================================================================
class InjectionReceipt(BaseDoc):
    order = models.ForeignKey(
        InjectionOrder,
        on_delete=models.PROTECT,
        related_name="receipts",
    )
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)

    # ✅ 배송그룹 FK (헤더 재사용 키)
    shipment_group = models.ForeignKey(
        PartnerShipmentGroup,
        on_delete=models.PROTECT,
        related_name="injection_receipts",
        null=False, blank=False,
    )

    # 사용 여부/시각 (출고만 했으면 False, 실제 사용 시 True)
    is_used = models.BooleanField(default=False)
    used_at = models.DateTimeField(null=True, blank=True)

    # 추적성 보조: 발주 LOT 스냅샷(표시/검색 편의)
    order_lot_snapshot = models.CharField(max_length=40, blank=True)

    class Meta:
        db_table = "purchase_injectionreceipt"
        indexes = [
            models.Index(fields=["date", "receipt_lot"]),
            models.Index(fields=["is_active", "is_deleted"]),
            models.Index(fields=["is_used", "warehouse"]),
            models.Index(fields=["order"]),
            models.Index(fields=["shipment_group"]),  # ✅ 배송그룹 조회 최적화
        ]
        constraints = [
            CheckConstraint(check=Q(qty__gt=0), name="injrec_qty_positive"),
            CheckConstraint(
                check=Q(is_used=True) | Q(used_at__isnull=True),
                name="injrec_used_time_consistent",
            ),
            UniqueConstraint(fields=["receipt_lot"], name="uniq_injectionreceipt_receipt_lot"),
        ]

    def __str__(self):
        return f"[IN-REC] {self.receipt_lot} / qty={self.qty} / wh={self.warehouse_id}"


# =============================================================================
# 사출: 입고 라인 (배송상세 라인별 서브 LOT)
#   - 각 라인은 하나의 수입검사 상세(PASS)와 1:1 연결 (중복입고 방지)
#   - 1차(완화): sub_seq/sub_lot NULL 허용 → 백필 후 NOT NULL+UNIQUE로 격상
# =============================================================================
class InjectionReceiptLine(models.Model):
    receipt = models.ForeignKey(
        "InjectionReceipt",
        on_delete=models.PROTECT,
        related_name="lines",
        verbose_name="입고 헤더",
    )
    # 검사 상세(PASS)와 1:1
    detail  = models.OneToOneField(
        IncomingInspectionDetail,
        on_delete=models.PROTECT,
        related_name="receipt_line",
        verbose_name="검사 라인(PASS)",
    )
    qty     = models.PositiveIntegerField(verbose_name="입고 수량")
    created_at = models.DateTimeField(auto_now_add=True)

    # ── 서브 LOT
    # sub_seq : 헤더 내 일련번호(1,2,3…)
    # sub_lot : 화면/바코드용 표기(예: IN20251018001-01)
    sub_seq = models.PositiveIntegerField(null=False)                 # 1차(완화)
    sub_lot = models.CharField(max_length=32, unique=True, null=False)  # 1차(완화)

    class Meta:
        verbose_name = "사출 입고 라인"
        verbose_name_plural = "사출 입고 라인"
        db_table = "purchase_injectionreceiptline"
        indexes = [
            models.Index(fields=["receipt"]),
            models.Index(fields=["detail"]),
            models.Index(fields=["sub_lot"]),
        ]
        constraints = [
            UniqueConstraint(fields=["receipt", "sub_seq"], name="uniq_injrec_line_seq_per_receipt"),
            CheckConstraint(check=Q(qty__gt=0), name="injrec_line_qty_positive"),
        ]

    def __str__(self):
        return f"Receipt#{self.receipt_id} <- Detail#{self.detail_id} ({self.qty}) / {self.sub_lot}"


# =============================================================================
# 사출: 출고(창고 이동)
# =============================================================================
class InjectionIssue(BaseDoc):
    receipt = models.ForeignKey(
        "InjectionReceipt",
        on_delete=models.PROTECT,
        related_name="issues",
    )
    from_warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT, related_name="issue_from"
    )
    to_warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT, related_name="issue_to"
    )

    # 이동 시점에 사용처리까지 했는지(선택)
    is_used_at_issue = models.BooleanField(default=False)

    class Meta:
        db_table = "purchase_injectionissue"
        indexes = [
            models.Index(fields=["date", "receipt_lot"]),
            models.Index(fields=["from_warehouse", "to_warehouse"]),
            models.Index(fields=["receipt"]),
        ]
        constraints = [
            CheckConstraint(check=Q(qty__gt=0), name="injissue_qty_positive"),
            CheckConstraint(check=~Q(from_warehouse=F("to_warehouse")), name="injissue_diff_wh"),
            UniqueConstraint(fields=["receipt_lot"], name="uniq_injectionissue_receipt_lot"),
        ]

    def __str__(self):
        return f"[INJ-ISSUE] {self.receipt_lot} / qty={self.qty} / {self.from_arehouse_id}->{self.to_warehouse_id}"


# =============================================================================
# 통합(약품/비철/부자재): 입고/출고/반품 + 발주 (기존 구조 유지)
# =============================================================================
CATEGORY_CHOICES = (
    ("CHEM", "약품"),
    ("NF",   "비철"),
    ("SUP",  "부자재"),
)


class UnifiedReceipt(BaseDoc):
    """약품/비철/부자재 공통 입고 전표"""
    category = models.CharField(max_length=8, choices=CATEGORY_CHOICES, db_index=True)
    vendor   = models.ForeignKey(Vendor, on_delete=models.PROTECT, related_name="unified_receipts")

    # 품목(Generic FK)
    item_ct  = models.ForeignKey(ContentType, on_delete=models.PROTECT)
    item_id  = models.PositiveBigIntegerField()
    item     = GenericForeignKey("item_ct", "item_id")

    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="unified_receipts")

    is_used = models.BooleanField(default=False)
    used_at = models.DateTimeField(null=True, blank=True)

    # 스냅샷
    item_name_snapshot = models.CharField(max_length=200)
    spec_snapshot      = models.CharField(max_length=200, blank=True)
    extra              = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "purchase_receipt"
        indexes = [
            models.Index(fields=["category", "date"]),
            models.Index(fields=["category", "warehouse"]),
            models.Index(fields=["category", "vendor"]),
            models.Index(fields=["item_ct", "item_id"]),
        ]
        constraints = [
            CheckConstraint(check=Q(qty__gt=0), name="unirec_qty_positive"),
            CheckConstraint(check=Q(is_used=True) | Q(used_at__isnull=True),
                            name="unirec_used_time_consistent"),
            UniqueConstraint(fields=["receipt_lot"], name="uniq_unifiedreceipt_receipt_lot"),
        ]
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"[{self.category}] {self.receipt_lot} / {self.item_name_snapshot}"


class UnifiedIssue(BaseDoc):
    """약품/비철/부자재 공통 출고(창고이동) 전표"""
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

    def __str__(self):
        return f"[{self.category}] {self.receipt_lot} / {self.from_warehouse_id}->{self.to_warehouse_id}"


class UnifiedReturn(BaseDoc):
    """약품/비철/부자재 공통 반품 전표"""
    category = models.CharField(max_length=8, choices=CATEGORY_CHOICES, db_index=True)
    receipt  = models.ForeignKey("UnifiedReceipt", on_delete=models.PROTECT, related_name="returns")
    from_warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="unified_returns_from")

    # 사유/코드(옵션)
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

    def __str__(self):
        return f"[{self.category}] {self.receipt_lot} / RETURN of {self.receipt_id}"


# =============================================================================
# 통합 발주(헤더/아이템) — 기존 구조 유지
# =============================================================================
class UnifiedOrderStatus(models.TextChoices):
    NEW = "NEW", "발주"
    CNL = "CNL", "취소"


class UnifiedFlowStatus(models.TextChoices):
    NG  = "NG",  "미입고"
    PRT = "PRT", "부분입고"
    RCV = "RCV", "입고완료"


class UnifiedOrder(models.Model):
    """통합 발주 헤더"""
    category = models.CharField(max_length=8, choices=CATEGORY_CHOICES, db_index=True)
    vendor   = models.ForeignKey(Vendor, on_delete=models.PROTECT, related_name="unified_orders")

    order_lot   = models.CharField(max_length=20, unique=True, db_index=True)  # 예: PO202509130001
    order_date  = models.DateField(db_index=True)
    due_date    = models.DateField(null=True, blank=True)

    order_status = models.CharField(max_length=3, choices=UnifiedOrderStatus.choices,
                                    default=UnifiedOrderStatus.NEW, db_index=True)
    flow_status  = models.CharField(max_length=3, choices=UnifiedFlowStatus.choices,
                                    default=UnifiedFlowStatus.NG, db_index=True)

    # 취소/감사
    cancel_at    = models.DateTimeField(null=True, blank=True)
    cancel_by    = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="cancelled_unified_orders",
    )
    cancel_reason = models.CharField(max_length=200, blank=True)

    # 생성/수정 메타
    created_by   = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="unified_orders_created",
    )
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_by   = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="unified_orders_updated",
    )
    updated_at   = models.DateTimeField(auto_now=True)

    # 운영 플래그
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

    def __str__(self):
        return f"[{self.category}] {self.order_lot} / {self.vendor_id}"


class UnifiedOrderItem(models.Model):
    """통합 발주 아이템"""
    order = models.ForeignKey(UnifiedOrder, on_delete=models.CASCADE, related_name="items")

    # 품목(GFK)
    item_ct = models.ForeignKey(ContentType, on_delete=models.PROTECT)
    item_id = models.PositiveBigIntegerField()
    item    = GenericForeignKey("item_ct", "item_id")

    # 수량/금액
    qty         = models.PositiveIntegerField()
    unit_price  = models.DecimalField(max_digits=14, decimal_places=4, default=0)
    amount      = models.DecimalField(max_digits=16, decimal_places=4, default=0)  # = qty * unit_price

    # 입고 예정일(사출 리스트와 동일 칼럼명 대응)
    expected_date = models.DateField(null=True, blank=True)

    # 스냅샷
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

    def __str__(self):
        return f"PO[{self.order_id}] x {self.qty}"