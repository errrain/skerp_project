from django.db import models
from vendor.models import Vendor  # 고객사


class Chemical(models.Model):
    name = models.CharField("품명", max_length=100)
    spec = models.CharField("규격", max_length=100, blank=True, null=True)
    customer = models.ForeignKey(Vendor, on_delete=models.SET_NULL, blank=True, null=True, verbose_name="고객사", related_name="nonferrous_set")
    image = models.ImageField("제품 이미지", upload_to="nonferrous/images/", blank=True, null=True)

    use_yn = models.CharField("사용여부", max_length=1, choices=[('Y', '사용'), ('N', '미사용')], default='Y')
    delete_yn = models.CharField("삭제여부", max_length=1, choices=[('N', '정상'), ('Y', '삭제')], default='N')
    created_dt = models.DateTimeField("등록일시", auto_now_add=True)
    updated_dt = models.DateTimeField("수정일시", auto_now=True)
    created_by = models.CharField("등록자", max_length=50, blank=True, null=True)
    updated_by = models.CharField("수정자", max_length=50, blank=True, null=True)

    def __str__(self):
        return self.name

    def latest_price(self):
        return self.nonferrousprice_set.order_by('-date').first()


class ChemicalPrice(models.Model):
    nonferrous = models.ForeignKey(Chemical, on_delete=models.CASCADE, related_name='prices', verbose_name="약품")
    price = models.PositiveIntegerField("단가")
    date = models.DateTimeField("일자")
    created_by = models.CharField("등록자", max_length=50)
    created_dt = models.DateTimeField("등록일시", auto_now_add=True)

    class Meta:
        ordering = ['-date']  # 최신순 정렬

    def __str__(self):
        return f"{self.nonferrous.name} - {self.price}원 ({self.date.strftime('%Y-%m-%d')})"
