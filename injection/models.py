from django.db import models
from django.conf import settings
from django.utils import timezone
from vendor.models import Vendor  # 사출업체 연동

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

    name = models.CharField("품명", max_length=200)
    alias = models.CharField("별칭", max_length=100, blank=True, null=True)
    spec = models.CharField("규격", max_length=200)
    status = models.CharField("상태", max_length=10, choices=STATUS_CHOICES)
    part_number = models.CharField("Part Number", max_length=100, blank=True, null=True)
    sub_part_number = models.CharField("Sub Part Number", max_length=100, blank=True, null=True)
    part_size = models.CharField("Part Size", max_length=100, blank=True, null=True)
    material = models.CharField("소재", max_length=10, choices=MATERIAL_CHOICES, blank=True, null=True)
    vendor = models.ForeignKey(Vendor, verbose_name="사출업체", on_delete=models.SET_NULL, blank=True, null=True)
    image = models.ImageField("제품 이미지", upload_to="injection/images/", blank=True, null=True)

    use_yn = models.CharField("사용 여부", max_length=1, choices=[('Y', '사용'), ('N', '미사용')], default='Y')
    delete_yn = models.CharField("삭제 여부", max_length=1, choices=[('N', '정상'), ('Y', '삭제')], default='N')

    def __str__(self):
        return self.name


class MoldHistory(models.Model):
    injection = models.ForeignKey(Injection, on_delete=models.CASCADE, related_name='mold_histories', verbose_name='사출품')
    history_date = models.DateField("이력일자")
    content = models.TextField("이력 내용", blank=True, null=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, verbose_name='등록자')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = '금형 이력'
        verbose_name_plural = '금형 이력 목록'
        ordering = ['-history_date']

    def __str__(self):
        return f"{self.injection.name} - {self.history_date}"


class InjectionPrice(models.Model):
    injection = models.ForeignKey(Injection, on_delete=models.CASCADE, related_name='prices', verbose_name="사출품")
    date = models.DateField("일자")
    price = models.PositiveIntegerField("단가")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, verbose_name="등록자")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date']

    def __str__(self):
        return f"{self.injection.name} - {self.price}원 ({self.date})"
