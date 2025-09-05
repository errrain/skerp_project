# purchase/models.py
from django.db import models
from django.conf import settings
from django.db.models import Q, F, CheckConstraint
from injectionorder.models import InjectionOrder
from master.models import Warehouse  # ✅ master 앱 Warehouse 사용


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
        ]

    def __str__(self):
        return f"[INJ-ISSUE] {self.receipt_lot} / qty={self.qty} / {self.from_warehouse_id}->{self.to_warehouse_id}"
