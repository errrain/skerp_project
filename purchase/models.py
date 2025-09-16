# purchase/models.py
from django.db import models
from django.conf import settings
from django.db.models import Q, F, CheckConstraint, UniqueConstraint
from injectionorder.models import InjectionOrder
from master.models import Warehouse  # ✅ master 앱 Warehouse 사용

# ① [추가 import] ─────────────────────────────────────────────
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from vendor.models import Vendor  # DB에 vendor_vendor 테이블 존재(이름/상태/로그인 등)  # noqa

# ② [추가 상수] ──────────────────────────────────────────────
CATEGORY_CHOICES = (
    ("CHEM", "약품"),
    ("NF",   "비철"),
    ("SUP",  "부자재"),
)


# ───────────────────────────────────────────────────────────────────────────────
# 공통 베이스 (입고/출고/반품 등 확장용)
# - receipt_lot : 문서/전표 성격의 LOT (입고: INYYYYMMDDNN, 출고: IS..., 등)
# - date        : 전표 날짜
# - qty         : 수량(양수 제약)
# - remark      : 비고
# - created_by  : 작성자
# - is_active,is_deleted : 운영 플래그
# ───────────────────────────────────────────────────────────────────────────────
class BaseDoc(models.Model):
    receipt_lot = models.CharField(max_length=20, db_index=True)   # INYYYYMMDDNN 등
    date = models.DateField()
    qty = models.PositiveIntegerField(default=0)
    remark = models.CharField(max_length=200, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="%(class)s_created"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    # 운영 플래그
    is_active = models.BooleanField(default=True)
    is_deleted = models.BooleanField(default=False)

    class Meta:
        abstract = True


# ───────────────────────────────────────────────────────────────────────────────
# ✅ 사출 입고 모델
# 문서 정의: 위치정보(warehouse) + 사용여부(is_used) + 사용시각(used_at)을 보유
# 출고는 위치 이동(wh 변경)만 수행, 사용은 별도 시점에 True/used_at 기록
# ───────────────────────────────────────────────────────────────────────────────
class InjectionReceipt(BaseDoc):
    order = models.ForeignKey(
        InjectionOrder,
        on_delete=models.PROTECT,
        related_name="receipts"
    )
    # 현재 위치(창고)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)

    # 사용 여부/시각
    is_used = models.BooleanField(default=False)           # 출고만 했으면 False 유지
    used_at = models.DateTimeField(null=True, blank=True)  # 실제 사용 시점 기록

    # 추적성: 발주 LOT 스냅샷(표시/검색 편의)
    order_lot_snapshot = models.CharField(max_length=40, blank=True)

    class Meta:
        db_table = "purchase_injectionreceipt"
        indexes = [
            models.Index(fields=["date", "receipt_lot"]),
            models.Index(fields=["is_active", "is_deleted"]),
            models.Index(fields=["is_used", "warehouse"]),
            models.Index(fields=["order"]),  # 조회 최적화
        ]
        constraints = [
            CheckConstraint(check=Q(qty__gt=0), name="injrec_qty_positive"),
            # is_used=False 상태에서는 used_at이 비어 있어야 함
            CheckConstraint(
                check=Q(is_used=True) | Q(used_at__isnull=True),
                name="injrec_used_time_consistent",
            ),
            UniqueConstraint(fields=["receipt_lot"], name="uniq_injectionreceipt_receipt_lot"),
        ]

    def __str__(self):
        return f"[IN-REC] {self.receipt_lot} / qty={self.qty} / wh={self.warehouse_id}"


# ───────────────────────────────────────────────────────────────────────────────
# ✅ 사출 출고(이동) 이력
# - receipt : 대상 입고 레코드
# - from_warehouse → to_warehouse : 위치 이동
# - qty : 이동 수량(부분출고 가능)
# - is_used_at_issue : 이동 시점에 '사용 처리'까지 같이 했는지 여부(기본 False)
# 출고 등록 시, InjectionReceipt.warehouse 를 to_warehouse 로 업데이트.
# 사용은 별도로 InjectionReceipt.is_used/used_at 업데이트.
# ───────────────────────────────────────────────────────────────────────────────
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
            # 같은 창고로의 이동 금지
            CheckConstraint(
                check=~Q(from_warehouse=F("to_warehouse")),
                name="injissue_diff_wh",
            ),
            UniqueConstraint(fields=["receipt_lot"], name="uniq_injectionissue_receipt_lot"),
        ]

    def __str__(self):
        return f"[INJ-ISSUE] {self.receipt_lot} / qty={self.qty} / {self.from_warehouse_id}->{self.to_warehouse_id}"


# ③ [신규 모델] 약품/비철/부자재 공통 '입고' 전표 ─────────────
class UnifiedReceipt(BaseDoc):
    """
    약품/비철/부자재 공통 입고 전표 (사출과 분리)
    - BaseDoc.receipt_lot : INyyyyMMddNN (LOT 헬퍼는 view에서 호출해 할당)
    """
    category = models.CharField(max_length=8, choices=CATEGORY_CHOICES, db_index=True)
    vendor   = models.ForeignKey(Vendor, on_delete=models.PROTECT, related_name="unified_receipts")

    # 품목 마스터(각 앱) 참조 – 1단계: GenericForeignKey
    item_ct  = models.ForeignKey(ContentType, on_delete=models.PROTECT)
    item_id  = models.PositiveBigIntegerField()
    item     = GenericForeignKey("item_ct", "item_id")

    # ⚠️ BaseDoc에 이미 있는 필드들은 재정의 금지(중복 X)
    # date    = models.DateField(db_index=True)       # <---- 여기(중복 금지: BaseDoc에 이미 있음)
    warehouse  = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="unified_receipts")

    # 사용/추적 플래그
    is_used = models.BooleanField(default=False)
    used_at = models.DateTimeField(null=True, blank=True)

    # 스냅샷(회계/감사 용; 표시값 보존)
    item_name_snapshot = models.CharField(max_length=200)
    spec_snapshot      = models.CharField(max_length=200, blank=True)
    extra              = models.JSONField(default=dict, blank=True)  # 약품 확장(초기 JSONB)

    class Meta:
        db_table = "purchase_receipt"   # injection과 테이블 분리
        indexes = [
            models.Index(fields=["category", "date"]),
            models.Index(fields=["category", "warehouse"]),
            models.Index(fields=["category", "vendor"]),
            models.Index(fields=["item_ct", "item_id"]),
        ]
        constraints = [
            CheckConstraint(check=Q(qty__gt=0), name="unirec_qty_positive"),
            # is_used=False 상태에서는 used_at이 비어 있어야 함
            CheckConstraint(
                check=Q(is_used=True) | Q(used_at__isnull=True),
                name="unirec_used_time_consistent",
            ),
            UniqueConstraint(fields=["receipt_lot"], name="uniq_unifiedreceipt_receipt_lot"),
        ]
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"[{self.category}] {self.receipt_lot} / {self.item_name_snapshot}"


# ④ [신규 모델] 약품/비철/부자재 공통 '출고(창고이동)' 전표 ────
class UnifiedIssue(BaseDoc):
    """
    약품/비철/부자재 공통 출고(창고이동) 전표 (사출과 분리)
    - BaseDoc.receipt_lot : ISyyyyMMddNN (LOT 헬퍼는 view에서 호출해 할당)
    """
    category  = models.CharField(max_length=8, choices=CATEGORY_CHOICES, db_index=True)
    receipt   = models.ForeignKey(UnifiedReceipt, on_delete=models.PROTECT, related_name="issues")

    # ⚠️ BaseDoc 중복 금지
    # date   = models.DateField(db_index=True)        # <---- 여기(중복 금지: BaseDoc에 이미 있음)
    # qty    = models.PositiveIntegerField()          # <---- 여기(중복 금지: BaseDoc에 이미 있음)
    # remark = models.CharField(max_length=200, blank=True)  # <---- 여기(중복 금지: BaseDoc에 이미 있음)

    from_warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="unified_issues_from")
    to_warehouse   = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="unified_issues_to")

    # 선택: 이동 시점에 '사용 처리'까지 같이 했는지
    is_used_at_issue = models.BooleanField(default=False)

    class Meta:
        db_table = "purchase_issue"     # injection과 테이블 분리
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

# ⑤ [신규 모델] 약품/비철/부자재 공통 '반품' 전표 ────
class UnifiedReturn(BaseDoc):
    """
    약품/비철/부자재 공통 반품 전표 (사출과 분리)
    - LOT(전표번호): BaseDoc.receipt_lot (예: OTYYYYMMDDNN)  ← LOT 생성은 view에서 헬퍼 사용
    - 현재 단계: 전량 반품만 허용(부분반품은 차기)
    """
    category = models.CharField(max_length=8, choices=CATEGORY_CHOICES, db_index=True)
    receipt  = models.ForeignKey(UnifiedReceipt, on_delete=models.PROTECT, related_name="returns")
    # 반품은 '창고에서 벤더로' 나가는 개념이므로, 출발창고만 기록
    from_warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="unified_returns_from")

    # ⚠️ BaseDoc에 이미 있는 필드들은 재정의 금지
    # date   = models.DateField()
    # qty    = models.PositiveIntegerField()
    # remark = models.CharField(...)

    # 사유/코드(옵션)
    reason_code = models.CharField(max_length=40, blank=True)

    class Meta:
        db_table = "purchase_return"   # injection_* 과 테이블 분리
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

    # ======================================================================
    # ⑥ 통합 발주 (약품/비철/부자재) - 헤더/아이템
    #  - 사출과 달리 협력사 배송/수입검사 없음
    #  - 발주 상태 NEW/CNL, 진행상태 NG/PRT/RCV (간단 3단계)
    #  - 목록 템플릿(order_list.html)과 동일 칼럼 호환(취소/등록/수정 일시, 사용자 등)
    # ======================================================================

# 상태 선택지
class UnifiedOrderStatus(models.TextChoices):
    NEW = "NEW", "발주"
    CNL = "CNL", "취소"

class UnifiedFlowStatus(models.TextChoices):
    NG = "NG", "미입고"
    PRT = "PRT", "부분입고"
    RCV = "RCV", "입고완료"

class UnifiedOrder(models.Model):
    """통합 발주 헤더 (사출과 분리)"""
    category = models.CharField(max_length=8, choices=CATEGORY_CHOICES, db_index=True)
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT, related_name="unified_orders")

    order_lot = models.CharField(max_length=20, unique=True, db_index=True)  # 예: PO202509130001
    order_date = models.DateField(db_index=True)
    due_date = models.DateField(null=True, blank=True)

    # 상태(헤더)
    order_status = models.CharField(max_length=3, choices=UnifiedOrderStatus.choices,
                                    default=UnifiedOrderStatus.NEW, db_index=True)
    flow_status = models.CharField(max_length=3, choices=UnifiedFlowStatus.choices,
                                   default=UnifiedFlowStatus.NG, db_index=True)

    # 취소/감사
    cancel_at = models.DateTimeField(null=True, blank=True)
    cancel_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="cancelled_unified_orders"
    )
    cancel_reason = models.CharField(max_length=200, blank=True)

    # 생성/수정 메타
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="unified_orders_created"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="unified_orders_updated"
    )
    updated_at = models.DateTimeField(auto_now=True)

    # 운영 플래그
    is_active = models.BooleanField(default=True)
    is_deleted = models.BooleanField(default=False)

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
    """통합 발주 아이템 (품목 GFK + 스냅샷 + 금액)"""
    order = models.ForeignKey(UnifiedOrder, on_delete=models.CASCADE, related_name="items")

    # 품목(각 앱 마스터) GFK
    item_ct = models.ForeignKey(ContentType, on_delete=models.PROTECT)
    item_id = models.PositiveBigIntegerField()
    item = GenericForeignKey("item_ct", "item_id")

    # 수량/금액
    qty = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=14, decimal_places=4, default=0)
    amount = models.DecimalField(max_digits=16, decimal_places=4, default=0)  # = qty * unit_price

    # 입고 예정일(사출 리스트와 동일 칼럼명 대응)
    expected_date = models.DateField(null=True, blank=True)

    # 스냅샷
    item_name_snapshot = models.CharField(max_length=200)
    spec_snapshot = models.CharField(max_length=200, blank=True)

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

