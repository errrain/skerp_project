from django.db import models
from vendor.models import Vendor         # 고객사/사출사
from spec.models import Spec             # 제조사양
from injection.models import Injection
from submaterial.models import Submaterial

class Product(models.Model):
    STATUS_CHOICES = [
        ('개발', '개발'),
        ('양산', '양산'),
        ('서비스', '서비스'),
        ('단종', '단종'),
    ]

    MATERIAL_CHOICES = [
        ('ABS', 'ABS'),
        ('PC-ABS', 'PC-ABS'),
    ]

    USE_YN_CHOICES = [
        ('Y', '사용'),
        ('N', '미사용'),
    ]

    # 기본 정보
    name = models.CharField("품명", max_length=200)
    program_name = models.CharField("프로그램명", max_length=200)
    status = models.CharField("상태", max_length=10, choices=STATUS_CHOICES)
    alias = models.CharField("별칭", max_length=200, blank=True, null=True)
    part_number = models.CharField("Part Number", max_length=100, blank=True, null=True)
    sub_part_number = models.CharField("Sub Part Number", max_length=100, blank=True, null=True)
    part_size = models.CharField("Part Size", max_length=100, blank=True, null=True)
    material = models.CharField("소재", max_length=50, choices=MATERIAL_CHOICES, blank=True, null=True)

    # 연관 정보
    spec = models.ForeignKey(Spec, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="제조사양")
    customer = models.ForeignKey(Vendor, on_delete=models.SET_NULL, null=True, blank=True, related_name='products_as_customer', verbose_name="고객사")
    injection_vendor = models.ForeignKey(Vendor, on_delete=models.SET_NULL, null=True, blank=True, related_name='products_as_injection', verbose_name="사출사")

    # 물성 정보
    weight = models.CharField("무게 (g)", max_length=50, blank=True, null=True)
    rack_info = models.CharField("렉정보", max_length=100, blank=True, null=True)

    # 텍스트 사양
    finishing = models.CharField("Finishing", max_length=100, blank=True, null=True)
    grade = models.CharField("Grade", max_length=100, blank=True, null=True)
    injection_info = models.CharField("Injection", blank=True, null=True)
    plating = models.CharField("Plating", blank=True, null=True)
    assembly_packaging = models.CharField("Assembly/Packaging", blank=True, null=True)
    final_delivery = models.CharField("Final Delivery", blank=True, null=True)

    # 첨부 자료
    image = models.ImageField("제품 이미지", upload_to="product/images/", blank=True, null=True)
    ppap_file = models.FileField("PPAP DATA", upload_to="product/files/", blank=True, null=True)
    run_rate_file = models.FileField("RUN%RATE DATA", upload_to="product/files/", blank=True, null=True)
    transfer_file = models.FileField("양산이관 DATA", upload_to="product/files/", blank=True, null=True)

    # 관리
    use_yn = models.CharField("사용여부", max_length=1, choices=USE_YN_CHOICES, default='Y')
    delete_yn = models.CharField("삭제여부", max_length=1, choices=[('Y', '삭제'), ('N', '정상')], default='N')
    created_dt = models.DateTimeField("생성일시", auto_now_add=True)
    updated_dt = models.DateTimeField("수정일시", auto_now=True)
    created_by = models.CharField("생성자", max_length=50, blank=True, null=True)
    updated_by = models.CharField("수정자", max_length=50, blank=True, null=True)

    # 1. 신규 필드 추가
    production_program_code = models.CharField("생산 프로그램 번호", max_length=100, blank=True, null=True)
    hanger_count = models.PositiveIntegerField("투입 행거 수", blank=True, null=True)
    turn_time_per_hanger = models.PositiveIntegerField("행거당 생산 턴 시간 (분)", blank=True, null=True)
    rack_per_hanger = models.PositiveIntegerField("행거 당 렉 수량", blank=True, null=True)
    product_per_rack = models.PositiveIntegerField("렉당 제품 수량", blank=True, null=True)
    total_quantity = models.PositiveIntegerField("총 생산량", blank=True, null=True)
    total_time = models.PositiveIntegerField("총 생산시간 (분)", blank=True, null=True)

    package_quantity = models.PositiveIntegerField("패키지 수량", blank=True, null=True)

    # Product 모델에 ForeignKey 필드 추가
    injection_item = models.ForeignKey(
        Injection, on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name="사출품"
    )

    submaterial_item = models.ForeignKey(
        Submaterial, on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name="부자재"
    )

    def __str__(self):
        return f"{self.name} ({self.program_name})"

class ProductPrice(models.Model):
    product = models.ForeignKey("Product", on_delete=models.CASCADE, related_name='prices', verbose_name="제품")
    price = models.PositiveIntegerField("단가")
    date = models.DateTimeField("일자")
    created_by = models.CharField("등록자", max_length=50)
    created_dt = models.DateTimeField("등록일시", auto_now_add=True)

    class Meta:
        ordering = ['-date']  # 최신순 정렬

    def __str__(self):
        return f"{self.product.name} - {self.price}원 ({self.date.strftime('%Y-%m-%d')})"

class ProductSubmaterial(models.Model):
    product = models.ForeignKey("Product", on_delete=models.CASCADE, related_name="product_submaterials")
    submaterial = models.ForeignKey("submaterial.Submaterial", on_delete=models.CASCADE, verbose_name="부자재")
    quantity = models.PositiveIntegerField("소요 수량")

    def __str__(self):
        return f"{self.product.name} - {self.submaterial.name} x {self.quantity}"
