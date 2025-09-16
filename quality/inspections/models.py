# quality/inspections/models.py
from django.db import models
from django.contrib.postgres.fields import ArrayField
from django.utils import timezone


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
