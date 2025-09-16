# injectionorder/models.py
from django.db import models
from django.utils import timezone
from django.conf import settings
from django.db.models import Sum

from vendor.models import Vendor
from injection.models import Injection  # 사출품 모델


# -----------------------------
# 상태 코드 (DB에는 코드, 화면에는 한글 라벨)
# -----------------------------
class OrderStatus(models.TextChoices):
    NEW = "NEW", "발주"    # 주문(유효)
    CNL = "CNL", "취소"    # 주문취소


class FlowStatus(models.TextChoices):
    NG  = "NG",  "미입고"
    RDY = "RDY", "입고대기"
    PRT = "PRT", "부분입고"   # ✅ 신규
    RCV = "RCV", "입고완료"
    RET = "RET", "반출"


class InjectionOrder(models.Model):
    # 기본 식별/헤더
    order_lot = models.CharField(max_length=20, unique=True, verbose_name="발주 LOT")
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT, verbose_name="발주처")
    order_date = models.DateField(default=timezone.now, verbose_name="발주일")

    # 발주 상태축(주문/취소) – 삭제(dlt_yn)와 별개
    order_status = models.CharField(
        max_length=3,
        choices=OrderStatus.choices,
        default=OrderStatus.NEW,
        db_index=True,
        verbose_name="발주상태",
        help_text="주문/취소 상태(삭제 플래그와 별개)"
    )

    # 물류 진행 상태축(입고 흐름)
    flow_status = models.CharField(
        max_length=3,
        choices=FlowStatus.choices,
        default=FlowStatus.NG,
        db_index=True,
        verbose_name="진행상태",
        help_text="미입고/입고대기/부분입고/입고완료/반출"
    )

    # 협력사 배송등록 시각(입고대기 전환 기준)
    shipping_registered_at = models.DateTimeField(
        null=True, blank=True, verbose_name="배송등록 시각"
    )

    # 헤더 기본 입고예정일(라인별 expected_date가 있어도 목록/검색 성능 위해 헤더값 운용)
    due_date = models.DateField(null=True, blank=True, verbose_name="입고 예정일(헤더)")

    # 취소 메타(주문취소 이력)
    cancel_at = models.DateTimeField(null=True, blank=True, verbose_name="취소일시")
    cancel_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="cancelled_injection_orders", verbose_name="취소자"
    )
    cancel_reason = models.CharField(max_length=200, blank=True, verbose_name="취소사유")

    # 사용/삭제 플래그 (YN 규칙 통일)
    use_yn = models.CharField(max_length=1, default="Y", verbose_name="사용여부")   # 'Y'/'N'
    dlt_yn = models.CharField(max_length=1, default="N", verbose_name="삭제여부")   # 'Y'/'N'

    # 생성/수정 메타
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="생성일시")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="created_injection_orders", verbose_name="작성자"
    )
    updated_at = models.DateTimeField(auto_now=True, verbose_name="수정일시")
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="updated_injection_orders", verbose_name="수정자"
    )

    class Meta:
        verbose_name = "사출 발주"
        verbose_name_plural = "사출 발주"
        indexes = [
            models.Index(fields=["vendor", "order_status"], name="injord_vendor_orderstatus_idx"),
            models.Index(fields=["flow_status"], name="injord_flowstatus_idx"),
            models.Index(fields=["order_date"], name="injord_orderdate_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(use_yn__in=["Y", "N"]),
                name="chk_injectionorder_use_yn_YN",
            ),
            models.CheckConstraint(
                check=models.Q(dlt_yn__in=["Y", "N"]),
                name="chk_injectionorder_dlt_yn_YN",
            ),
        ]

    def __str__(self):
        return self.order_lot

    # -----------------------------
    # 편의 프로퍼티/헬퍼
    # -----------------------------
    @property
    def is_cancelled(self) -> bool:
        return self.order_status == OrderStatus.CNL

    @property
    def can_cancel(self) -> bool:
        """입고 진행 전(NG) + 아직 취소 전(NEW)일 때만 취소 허용"""
        return self.order_status == OrderStatus.NEW and self.flow_status == FlowStatus.NG

    def mark_cancelled(self, user=None, reason: str = ""):
        """주문취소 처리(삭제 아님)"""
        if not self.can_cancel:
            raise ValueError("입고 진행 중이거나 이미 취소된 발주는 취소할 수 없습니다.")
        self.order_status = OrderStatus.CNL
        self.cancel_at = timezone.now()
        self.cancel_by = user
        self.cancel_reason = reason or ""
        # dlt_yn 은 변경하지 않음 (취소건도 목록/통계에 노출)
        self.save(update_fields=[
            "order_status", "cancel_at", "cancel_by", "cancel_reason", "updated_at"
        ])

    @property
    def is_actionable_for_vendor(self) -> bool:
        """
        협력사 화면에서 '배송등록' 가능 여부
        - 주문이 유효(NEW)하고
        - 미입고(NG) 또는 반출(RET)일 때만 허용
        """
        return (
            self.order_status == OrderStatus.NEW and
            self.flow_status in (FlowStatus.NG, FlowStatus.RET)
        )

    def mark_shipping_registered(self):
        """
        배송등록 처리:
        - 주문 유효(NEW) & 미입고/반출 → 입고대기(RDY) + 시각 기록
        """
        if self.order_status != OrderStatus.NEW:
            raise ValueError("취소된 발주는 배송등록할 수 없습니다.")
        if self.flow_status in (FlowStatus.NG, FlowStatus.RET):
            self.flow_status = FlowStatus.RDY
            self.shipping_registered_at = timezone.now()
            self.save(update_fields=["flow_status", "shipping_registered_at", "updated_at"])

    # ---- (임시 호환) 기존 템플릿에서 item.order.status 접근시 라벨 반환
    @property
    def status(self) -> str:
        """기존 'status' 사용처 호환: 진행상태 한글 라벨을 반환"""
        return self.get_flow_status_display()

    # ---- 부분입고 반영 편의
    @property
    def is_fully_received(self) -> bool:
        """모든 라인이 잔량 0이면 True"""
        items = self.items.filter(dlt_yn="N")
        if not items.exists():
            return False
        return all(i.remaining_qty == 0 for i in items)

    @property
    def last_receipt_at(self):
        r = self.io_receipts.filter(dlt_yn="N").order_by("-receipt_date", "-id").first()
        return r.receipt_date if r else None

    def apply_flow_status_by_receipts(self):
        """
        입고 기록을 근거로 flow_status를 자동 반영:
        - 입고기록 1개 이상: PRT(부분입고) 또는 RCV(완료)
        - 기록 없음 + 배송등록만 된 경우: RDY
        - 그 외: NG
        """
        if self.io_receipts.filter(dlt_yn="N").exists():
            self.flow_status = FlowStatus.RCV if self.is_fully_received else FlowStatus.PRT
        else:
            self.flow_status = FlowStatus.RDY if self.shipping_registered_at else FlowStatus.NG
        self.save(update_fields=["flow_status", "updated_at"])


class InjectionOrderItem(models.Model):
    order = models.ForeignKey(
        InjectionOrder, on_delete=models.CASCADE, related_name="items", verbose_name="발주"
    )
    injection = models.ForeignKey(Injection, on_delete=models.PROTECT, verbose_name="사출품")
    quantity = models.PositiveIntegerField(verbose_name="발주 수량")
    expected_date = models.DateField(verbose_name="입고 예정일")
    unit_price = models.PositiveIntegerField(verbose_name="단가")       # 발주 당시 단가
    total_price = models.PositiveIntegerField(verbose_name="합계금액")   # 단가 * 수량

    # 선택: 라인 단위 감사추적
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="생성일시")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="created_injection_order_items", verbose_name="작성자"
    )
    updated_at = models.DateTimeField(auto_now=True, verbose_name="수정일시")
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="updated_injection_order_items", verbose_name="수정자"
    )

    # 라인 소프트삭제
    dlt_yn = models.CharField(max_length=1, default="N", verbose_name="삭제여부")  # 'Y'/'N'

    class Meta:
        verbose_name = "사출 발주 품목"
        verbose_name_plural = "사출 발주 품목"
        indexes = [
            models.Index(fields=["order"], name="injitem_order_idx"),
            models.Index(fields=["expected_date"], name="injitem_expected_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(dlt_yn__in=["Y", "N"]),
                name="chk_injectionorderitem_dlt_yn_YN",
            ),
        ]

    def save(self, *args, **kwargs):
        self.total_price = (self.unit_price or 0) * (self.quantity or 0)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.order.order_lot} - {self.injection}"

    # --- 합계/잔량 프로퍼티 ---
    @property
    def received_qty(self) -> int:
        agg = self.io_receipts.filter(dlt_yn="N").aggregate(total=Sum("quantity"))
        return int(agg["total"] or 0)

    @property
    def remaining_qty(self) -> int:
        base = int(self.quantity or 0)
        return max(0, base - self.received_qty)


# -----------------------------
# 부분입고 기록(여러 건 누적)
# -----------------------------
class InjectionReceipt(models.Model):
    order = models.ForeignKey(
    InjectionOrder,
    on_delete=models.CASCADE,
    related_name="io_receipts",          # ← receipts  → io_receipts 로 변경
    related_query_name="io_receipt",     # ← 추가(권장)
    verbose_name="발주",
)
    item = models.ForeignKey(
        InjectionOrderItem, on_delete=models.CASCADE,
        related_name="receipts", verbose_name="발주 품목"
    )
    receipt_date = models.DateField(verbose_name="입고일")
    quantity = models.PositiveIntegerField(verbose_name="입고 수량")
    note = models.CharField(max_length=200, blank=True, verbose_name="비고")

    # 감사/소프트삭제 메타
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="생성일시")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        verbose_name="작성자"
    )
    dlt_yn = models.CharField(max_length=1, default="N", verbose_name="삭제여부")  # 'Y'/'N'

    class Meta:
        verbose_name = "사출 발주 입고기록"
        verbose_name_plural = "사출 발주 입고기록"
        indexes = [
            models.Index(fields=["order", "item", "receipt_date"], name="injrcpt_ord_item_date_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(dlt_yn__in=["Y", "N"]), name="chk_injectionreceipt_dlt_yn_YN"
            ),
        ]

    def __str__(self):
        return f"{self.order.order_lot} / {self.item_id} / {self.receipt_date} / {self.quantity}"

    def save(self, *args, **kwargs):
        """
        저장/정정 시 상위 발주의 진행상태를 최신화(PRT/RCV/NG/RDY).
        - 수량 검증(>0) 정도는 폼/뷰에서 처리 권장.
        """
        super().save(*args, **kwargs)
        # 상위 헤더 상태 자동 재계산
        self.order.apply_flow_status_by_receipts()


# (파일 하단, 어떤 클래스 내부도 아님)  ⬇⬇⬇
# --- 임시 호환: 기존 STATUS_CHOICES 참조 코드 대응 ---
STATUS_CHOICES = [
    (FlowStatus.NG,  FlowStatus.NG.label),
    (FlowStatus.RDY, FlowStatus.RDY.label),
    (FlowStatus.PRT, FlowStatus.PRT.label),  # ✅ 부분입고 추가
    (FlowStatus.RCV, FlowStatus.RCV.label),
    (FlowStatus.RET, FlowStatus.RET.label),
]
