from django.db import models
from django.contrib.postgres.fields import ArrayField
from django.utils import timezone

# 현업 확정 상태: 대기 → 합격/불합격/보류
class QCStatus(models.TextChoices):
    DRAFT = "DRAFT", "대기"
    PASS  = "PASS",  "합격"
    FAIL  = "FAIL",  "불합격"
    HOLD  = "HOLD",  "보류"

# 수입검사 불합격 사유 코드(다중 선택) - 코드/라벨 분리
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
    사출 발주(헤더, LOT 단위)에 대한 수입검사 1건.
    주문/거래처/품명/수량은 injectionorder 쪽 데이터를 참조해서 화면에 표시.
    """
    order = models.ForeignKey(
        "injectionorder.InjectionOrder",
        on_delete=models.PROTECT,
        related_name="incoming_inspections",
        verbose_name="발주",
    )

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

    # 코드값 길이 고려(max_length=20)
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
        ]

    def __str__(self):
        return f"IncomingInspection({self.order_id}, {self.status})"
