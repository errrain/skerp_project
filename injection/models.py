from django.db import models
from vendor.models import Vendor

class Injection(models.Model):
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

    DELETE_YN_CHOICES = [
        ('Y', '삭제'),
        ('N', '정상'),
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
    ton = models.CharField("사출기 톤수", max_length=50, blank=True, null=True)
    cycle_time = models.CharField("CYCLETIME", max_length=50, blank=True, null=True)
    weight = models.CharField("Weight (g)", max_length=50, blank=True, null=True)

    # 연관 정보
    vendor = models.ForeignKey(Vendor, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="사출사")

    # 첨부 자료
    image = models.ImageField("제품 이미지", upload_to="injection/images/", blank=True, null=True)

    # 관리
    use_yn = models.CharField("사용여부", max_length=1, choices=USE_YN_CHOICES, default='Y')
    delete_yn = models.CharField("삭제여부", max_length=1, choices=DELETE_YN_CHOICES, default='N')
    created_dt = models.DateTimeField("생성일시", auto_now_add=True)
    updated_dt = models.DateTimeField("수정일시", auto_now=True)
    created_by = models.CharField("생성자", max_length=50, blank=True, null=True)
    updated_by = models.CharField("수정자", max_length=50, blank=True, null=True)

    def __str__(self):
        return f"{self.name} ({self.program_name})"
