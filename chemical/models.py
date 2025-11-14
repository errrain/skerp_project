# chemical/models.py

from django.db import models
from vendor.models import Vendor  # 고객사


class StdConcUnit(models.TextChoices):
    G_L = "G_L", "g/L"
    ML_L = "ML_L", "ml/L"


class Chemical(models.Model):
    """
    규격은 자연어(spec)로 입력받되,
    - unit_qty: 단위규격(정수)
    - spec_unit: 측정 단위(코드; KG/L/MM/EA/...)
    - container_uom: 포장/용기 단위(말/통/드럼/EA 등)
    - spec_note: 성상/등급(예: 분말, SJ2)
    로 표준화 필드를 함께 저장한다.
    금액/바코드 로직은 다른 앱에서 처리하므로 여기선 보관만 책임진다.
    """
    name = models.CharField("품명", max_length=100)

    # 사용자가 친 자연어 (예: "18kg/말", "분말", "500mm SJ2")
    spec = models.CharField("규격(자연어)", max_length=200, blank=True, null=True)

    class SpecUnit(models.TextChoices):
        PCT = "PCT", "%"
        KG = "KG", "kg"
        G = "G", "g"
        L = "L", "L"
        ML = "ML", "mL"
        MM = "MM", "mm"
        CM = "CM", "cm"
        M = "M", "m"
        EA = "EA", "EA"

    # 표준화 필드
    unit_qty = models.PositiveIntegerField("단위규격(정수)", blank=True, null=True)
    spec_unit = models.CharField(
        "측정 단위",
        max_length=10,
        choices=SpecUnit.choices,
        blank=True,
        null=True,
    )
    container_uom = models.CharField(
        "포장단위(말/통/드럼/EA 등)", max_length=20, blank=True, null=True
    )
    spec_note = models.CharField(
        "규격 비고(성상/등급)", max_length=100, blank=True, null=True
    )

    # 실제 공정에서 사용할 단위/수량 (예: 4L → mL 기준 4000)
    use_unit = models.CharField(
        "사용 단위",
        max_length=10,
        choices=SpecUnit.choices,
        blank=True,
        null=True,
    )
    use_base_qty = models.PositiveIntegerField(
        "포장당 사용단위 수량",
        blank=True,
        null=True,
        help_text="예) 4L, 사용단위 mL → 4000",
    )

    # 기타 메타 정보
    customer = models.ForeignKey(
        Vendor,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        verbose_name="고객사",
    )
    image = models.ImageField(
        "제품 이미지", upload_to="chemical/images/", blank=True, null=True
    )

    # MSDS / TDS 파일
    msds_file = models.FileField(
        "MSDS 파일", upload_to="chemical/msds/", blank=True, null=True
    )
    tds_file = models.FileField(
        "TDS 파일", upload_to="chemical/tds/", blank=True, null=True
    )

    use_yn = models.CharField(
        "사용여부",
        max_length=1,
        choices=[("Y", "사용"), ("N", "미사용")],
        default="Y",
    )
    delete_yn = models.CharField(
        "삭제여부",
        max_length=1,
        choices=[("N", "정상"), ("Y", "삭제")],
        default="N",
    )
    created_dt = models.DateTimeField("등록일시", auto_now_add=True)
    updated_dt = models.DateTimeField("수정일시", auto_now=True)
    created_by = models.CharField("등록자", max_length=50, blank=True, null=True)
    updated_by = models.CharField("수정자", max_length=50, blank=True, null=True)

    class Meta:
        verbose_name = "약품"
        verbose_name_plural = "약품"

    def __str__(self):
        return self.name

    # 화면/리포트용 표준 표기
    def formatted_spec(self) -> str:
        parts = []
        if self.unit_qty and self.spec_unit:
            parts.append(f"{self.unit_qty}{self.get_spec_unit_display()}")
        if self.container_uom:
            parts.append(f"/{self.container_uom}")
        txt = "".join(parts)
        if self.spec_note:
            txt = f"{txt} {self.spec_note}".strip()
        return txt or (self.spec or "")

    # 최신 단가(있을 경우)
    def latest_price(self):
        # ChemicalPrice.Meta.ordering = ['-date'] 이므로 first()가 최신
        return self.prices.first()

    # 최신 표준농도(있을 경우)
    def latest_std_concentration(self):
        return self.std_concentrations.first()

    # 최신 관리범위(있을 경우)
    def latest_control_range(self):
        return self.control_ranges.first()


class ChemicalPrice(models.Model):
    chemical = models.ForeignKey(
        Chemical,
        on_delete=models.CASCADE,
        related_name="prices",
        verbose_name="약품",
    )
    price = models.PositiveIntegerField("단가")
    date = models.DateTimeField("일자")
    created_by = models.CharField("등록자", max_length=50)
    created_dt = models.DateTimeField("등록일시", auto_now_add=True)

    class Meta:
        ordering = ["-date"]  # 최신순 정렬
        verbose_name = "약품 단가"
        verbose_name_plural = "약품 단가"

    def __str__(self):
        d = self.date.strftime("%Y-%m-%d") if self.date else ""
        return f"{self.chemical.name} - {self.price}원 ({d})"


class ChemicalStdConcentration(models.Model):
    chemical = models.ForeignKey(
        Chemical,
        on_delete=models.CASCADE,
        related_name="std_concentrations",
        verbose_name="약품",
    )
    value = models.DecimalField("표준농도", max_digits=10, decimal_places=2)
    unit = models.CharField(
        "단위",
        max_length=10,
        choices=StdConcUnit.choices,
    )
    date = models.DateTimeField("일자")
    reason = models.CharField("변동사유", max_length=200, blank=True)
    created_by = models.CharField("등록자", max_length=50)
    created_dt = models.DateTimeField("등록일시", auto_now_add=True)

    class Meta:
        ordering = ["-date"]  # 최신순
        verbose_name = "표준농도"
        verbose_name_plural = "표준농도"

    def __str__(self):
        d = self.date.strftime("%Y-%m-%d") if self.date else ""
        return f"{self.chemical.name} - {self.value:.2f} {self.get_unit_display()} ({d})"


class ChemicalControlRange(models.Model):
    chemical = models.ForeignKey(
        Chemical,
        on_delete=models.CASCADE,
        related_name="control_ranges",
        verbose_name="약품",
    )
    lower_value = models.DecimalField("관리 하한", max_digits=10, decimal_places=2)
    upper_value = models.DecimalField("관리 상한", max_digits=10, decimal_places=2)
    avg_value = models.DecimalField("관리 평균", max_digits=10, decimal_places=2)
    unit = models.CharField(
        "단위",
        max_length=10,
        choices=StdConcUnit.choices,
    )
    date = models.DateTimeField("일자")
    reason = models.CharField("변동사유", max_length=200, blank=True)
    created_by = models.CharField("등록자", max_length=50)
    created_dt = models.DateTimeField("등록일시", auto_now_add=True)

    class Meta:
        ordering = ["-date"]  # 최신순
        verbose_name = "관리범위"
        verbose_name_plural = "관리범위"

    def __str__(self):
        d = self.date.strftime("%Y-%m-%d") if self.date else ""
        return (
            f"{self.chemical.name} - "
            f"{self.lower_value:.2f}~{self.upper_value:.2f}"
            f"({self.avg_value:.2f}) {self.get_unit_display()} ({d})"
        )
