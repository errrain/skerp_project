# quality/inspections/models.py
from django.db import models
from django.contrib.postgres.fields import ArrayField
from django.utils import timezone
from django.conf import settings

class QCStatus(models.TextChoices):
    DRAFT = "DRAFT", "대기"
    PASS  = "PASS",  "합격"
    FAIL  = "FAIL",  "불합격"
    HOLD  = "HOLD",  "보류"


# 수입검사 불합격 사유 코드(다중 선택)
DEFECT_CODE_CHOICES = [
    ("DEFECT_CD_01", "GAS"),
    ("DEFECT_CD_02", "은조"),
    ("DEFECT_CD_03", "찍힘"),
    ("DEFECT_CD_04", "긁힘"),
    ("DEFECT_CD_05", "수축"),
    ("DEFECT_CD_06", "Burr"),
    ("DEFECT_CD_07", "웰드"),
    ("DEFECT_CD_08", "미성형"),
    ("DEFECT_CD_09", "파손"),
    ("DEFECT_CD_10", "기타"),
]


class IncomingInspection(models.Model):
    """
    사출 발주에 대한 수입검사. (배송상세 단위 저장 지원)
    """
    order = models.ForeignKey(
        "injectionorder.InjectionOrder",
        on_delete=models.PROTECT,
        related_name="incoming_inspections",
        verbose_name="발주",
    )

    # 배송상세 식별자(최소 변경: 정수 ID 보관)
    shipment_id  = models.PositiveIntegerField(null=True, blank=True, db_index=True, verbose_name="배송상세ID")
    shipment_seq = models.PositiveIntegerField(null=True, blank=True, verbose_name="배송상세 순번")

    # 입력 항목
    inspection_date = models.DateField(default=timezone.now, verbose_name="수입검사일")

    production_date1 = models.DateField(null=True, blank=True, verbose_name="사출 생산일1")
    production_qty1  = models.PositiveIntegerField(null=True, blank=True, verbose_name="수량1")
    production_date2 = models.DateField(null=True, blank=True, verbose_name="사출 생산일2")
    production_qty2  = models.PositiveIntegerField(null=True, blank=True, verbose_name="수량2")
    production_date3 = models.DateField(null=True, blank=True, verbose_name="사출 생산일3")
    production_qty3  = models.PositiveIntegerField(null=True, blank=True, verbose_name="수량3")

    status = models.CharField(
        max_length=8,
        choices=QCStatus.choices,
        default=QCStatus.DRAFT,
        db_index=True,
        verbose_name="합격여부",
    )

    defects = ArrayField(
        base_field=models.CharField(max_length=20, choices=DEFECT_CODE_CHOICES),
        default=list,
        blank=True,
        verbose_name="불합격 사유코드",
    )

    inspect_qty = models.PositiveIntegerField(null=True, blank=True, verbose_name="수입검사 수량")
    return_qty  = models.PositiveIntegerField(null=True, blank=True, verbose_name="반출 수량")
    remark      = models.TextField(blank=True, verbose_name="비고")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "수입검사"
        verbose_name_plural = "수입검사"
        indexes = [
            models.Index(fields=["order", "status"]),
            models.Index(fields=["inspection_date"]),
            # 주문+배송상세 최신 검사 조회 최적화
            models.Index(fields=["order", "shipment_id", "created_at"]),
        ]

    def __str__(self):
        seq = f"#{self.shipment_seq}" if self.shipment_seq else ""
        return f"IncomingInspection(order={self.order_id}, ship={self.shipment_id}{seq}, status={self.status})"


class IncomingInspectionDetail(models.Model):
    """
    수입검사 라인(배송 라인 단위).
    - 헤더: IncomingInspection
    - 라인: PartnerShipmentLine (예: 배송상세 #2-1)
    - 입고 확정 시, PASS 라인을 그대로 IncomingReceiptLine으로 복사하면
      “입고 = 발주/배송상세/수량/PASS”를 FK로 완전히 추적 가능.
    """
    inspection = models.ForeignKey(
        "quality.IncomingInspection",
        on_delete=models.CASCADE,
        related_name="details",
        verbose_name="수입검사 헤더",
    )
    shipment_line = models.ForeignKey(
        "partnerorder.PartnerShipmentLine",
        on_delete=models.PROTECT,          # 추적성 보존(배송 라인 삭제 방지)
        related_name="qc_details",
        verbose_name="배송 라인",
    )

    # 스냅샷 필드(검사 시점의 값)
    qty = models.PositiveIntegerField(verbose_name="검사 대상 수량")
    status = models.CharField(
        max_length=8,
        choices=QCStatus.choices,
        default=QCStatus.DRAFT,
        db_index=True,
        verbose_name="합격여부",
    )
    defects = ArrayField(
        base_field=models.CharField(max_length=20, choices=DEFECT_CODE_CHOICES),
        default=list,
        blank=True,
        verbose_name="불합격 사유코드",
    )
    return_qty = models.PositiveIntegerField(default=0, verbose_name="반출 수량")
    remark = models.TextField(blank=True, verbose_name="비고")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "수입검사 라인"
        verbose_name_plural = "수입검사 라인"
        indexes = [
            models.Index(fields=["inspection"]),
            models.Index(fields=["shipment_line"]),
            models.Index(fields=["status"]),
        ]
        unique_together = [("inspection", "shipment_line")]  # 한 검사 헤더당 동일 배송 라인 중복 방지(선택)

    def __str__(self):
        return f"InspectionDetail(insp={self.inspection_id}, line={self.shipment_line_id}, qty={self.qty}, {self.status})"

# -------------------------------
# 출하검사(Outgoing) 정의
# -------------------------------
# 출하검사용 검사 상태(진행상태)
class OutgoingStatus(models.TextChoices):
    DRAFT = "DRAFT", "대기"        # 검사 중/아직 완료 아님
    DONE  = "DONE",  "완료"        # 검사 + 포장 완료 (잔량 없음)
    HOLD  = "HOLD",  "보류/잔량"   # 잔량을 다음 검사로 이월


# 출하검사 결과 (합격/불합격)
class InspectionResult(models.TextChoices):
    NONE = "NONE", "미결정"
    PASS = "PASS", "합격"
    FAIL = "FAIL", "불합격"

class OutgoingDefectGroup(models.TextChoices):
    PLATING = "PLATING", "도금불량"
    INJECTION = "INJECTION", "사출불량"

class OutgoingDefectCode(models.TextChoices):
    # ----- 도금불량 -----
    STAIN = "PL_STAIN", "얼룩"
    UNPLATED = "PL_UNPLATED", "미도금"
    SPOT_UNPLATED = "PL_SPOT_UNPLATED", "점미도금"
    NO_CHROME = "PL_NO_CHROME", "미크롬"
    COLOR_GLOSS = "PL_COLOR_GLOSS", "색상광택"
    BLISTER = "PL_BLISTER", "부풀음"
    PIT = "PL_PIT", "피트"
    FOREIGN = "PL_FOREIGN", "불순물"
    FOREIGN_ORGANIC = "PL_FOREIGN_ORG", "불순물유기"
    BURNING = "PL_BURNING", "도금탐"
    DENT_PLATING = "PL_DENT", "찍힘"
    SCRATCH_PLATING = "PL_SCRATCH", "긁힘"
    BUILDUP = "PL_BUILDUP", "도금뭉침"
    HANDLING = "PL_HANDLING", "취급"
    PROCESS = "PL_PROCESS", "공정"
    CRACK = "PL_CRACK", "크랙"
    STRIPE_PIT = "PL_STRIPE_PIT", "줄피트/면커버"
    OTHER_PLATING = "PL_OTHER", "기타(도금불량)"

    # ----- 사출불량 -----
    GAS = "IN_GAS", "GAS"
    SILVER = "IN_SILVER", "은조"
    DENT_INJECTION = "IN_DENT", "찍힘"
    SCRATCH_INJECTION = "IN_SCRATCH", "긁힘"
    SHRINK = "IN_SHRINK", "수축"
    BURR = "IN_BURR", "Burr"
    WELD = "IN_WELD", "웰드"
    OTHER_INJECTION = "IN_OTHER", "기타(사출불량)"

    @classmethod
    def group_of(cls, code: str) -> str:
        if code.startswith("PL_"):
            return OutgoingDefectGroup.PLATING
        return OutgoingDefectGroup.INJECTION


class OutgoingInspection(models.Model):
    """
    생산 완료된 작업 LOT에 대한 출하검사 헤더.
    - 기본 설계: 작업 LOT(WorkOrder) 1개당 출하검사 1건.
    """
    workorder = models.OneToOneField(
        "production.WorkOrder",
        on_delete=models.PROTECT,
        related_name="outgoing_inspection",
        verbose_name="작업 LOT",
    )

    inspection_date = models.DateField(
        default=timezone.now,
        verbose_name="출하검사일",
    )

    # --- 수량 정보(검사 시점 기준) ---
    # 실제 검사수량 = good + defect + loss
    inspect_qty = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="검사수량",
    )
    good_qty = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="양품수량",
    )
    defect_qty = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="불량수량",
    )
    loss_qty = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="LOSS 수량",
    )

    # HOLD 로 넘길 때 이월되는 양품 잔량
    hold_qty = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="잔량수량",
        help_text="HOLD 상태로 다음 검사로 넘기는 양품 잔여 수량",
    )

    # 실수량 조정 (계획수량 대비 ±EA)
    adjust_qty = models.IntegerField(
        default=0,
        verbose_name="실수량 조정수량(±EA)",
        help_text="계획수량(WorkOrder.order_qty) 대비 실제 실물 수량 증감",
    )
    adjust_reason = models.CharField(
        max_length=200,
        blank=True,
        verbose_name="실수량 조정 사유",
    )

    # 검사 진행 상태 (출하검사용)
    status = models.CharField(
        max_length=8,
        choices=OutgoingStatus.choices,
        default=OutgoingStatus.DRAFT,
        db_index=True,
        verbose_name="검사 상태",
    )

    # 검사 결과 (합격/불합격)
    result = models.CharField(
        max_length=8,
        choices=InspectionResult.choices,
        default=InspectionResult.NONE,
        verbose_name="검사 결과",
    )

    remark = models.TextField(
        blank=True,
        verbose_name="비고",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "출하검사"
        verbose_name_plural = "출하검사"
        indexes = [
            models.Index(fields=["inspection_date"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"OutgoingInspection(workorder={self.workorder_id}, status={self.status})"

    @property
    def is_completed(self) -> bool:
        """DRAFT 가 아니면 '검사완료' 로 간주."""
        return self.status != OutgoingStatus.DRAFT

class OutgoingInspectionDefect(models.Model):
    """
    출하검사 불량 항목별 수량.
    - 한 출하검사(헤더) 아래에 여러 불량 코드와 수량이 매핑됨.
    """
    inspection = models.ForeignKey(
        "quality.OutgoingInspection",
        on_delete=models.CASCADE,
        related_name="defects",
        verbose_name="출하검사",
    )

    code = models.CharField(
        max_length=32,
        choices=OutgoingDefectCode.choices,
        verbose_name="불량 코드",
    )

    qty = models.PositiveIntegerField(
        verbose_name="불량 수량",
    )

    class Meta:
        verbose_name = "출하검사 불량"
        verbose_name_plural = "출하검사 불량"
        indexes = [
            models.Index(fields=["inspection"]),
            models.Index(fields=["code"]),
        ]
        unique_together = [("inspection", "code")]

    def __str__(self):
        return f"OutgoingDefect(insp={self.inspection_id}, code={self.code}, qty={self.qty})"


    @property
    def group(self) -> OutgoingDefectGroup:
        """코드 값으로부터 도금불량/사출불량 대분류를 계산."""
        return OutgoingDefectCode.group_of(self.code)

class OutgoingFinishedLot(models.Model):
    inspection = models.ForeignKey(
        OutgoingInspection,
        on_delete=models.CASCADE,
        related_name="finished_lots",
        verbose_name="출하검사",
    )
    finished_lot = models.CharField("완성 LOT 번호", max_length=30)

    box_size = models.PositiveIntegerField("박스 수량", default=0)

    status = models.CharField(
        "포장상태",
        max_length=10,
        choices=[("FULL", "완성"), ("SHORT", "부족")],
        default="FULL",
    )

    shipped = models.BooleanField("출하여부", default=False)
    operator = models.CharField("작업자", max_length=50, blank=True, null=True)
    packed_at = models.DateTimeField("포장일시", auto_now_add=True)

    # ✅ SOFT DELETE 필드들
    dlt_yn = models.CharField("삭제여부", max_length=1, default="N")  # N / Y
    dlt_at = models.DateTimeField("삭제일시", null=True, blank=True)
    dlt_user = models.CharField("삭제자", max_length=50, null=True, blank=True)
    dlt_reason = models.CharField("삭제사유", max_length=200, null=True, blank=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["finished_lot"],
                name="uq_outgoingfinishedlot_finished_lot",
            )
        ]

    def __str__(self) -> str:
        return f"{self.finished_lot} ({self.box_size}ea)"