from django.db import models
from django.db import models
from vendor.models import Vendor
from injection.models import Injection  # 사출품 모델
from django.utils import timezone

class InjectionOrder(models.Model):
    order_lot = models.CharField(max_length=20, unique=True, verbose_name="발주 LOT")
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT, verbose_name="발주처")
    order_date = models.DateField(default=timezone.now, verbose_name="발주일")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    dlt_yn = models.CharField(max_length=1, choices=[('N', '정상'), ('Y', '삭제')], default='N')

    def __str__(self):
        return self.order_lot


class InjectionOrderItem(models.Model):
    order = models.ForeignKey(InjectionOrder, on_delete=models.CASCADE, related_name="items")
    injection = models.ForeignKey(Injection, on_delete=models.PROTECT, verbose_name="사출품")
    quantity = models.PositiveIntegerField(verbose_name="발주 수량")
    expected_date = models.DateField(verbose_name="입고 예정일")
    unit_price = models.PositiveIntegerField(verbose_name="단가")  # 발주 당시 단가
    total_price = models.PositiveIntegerField(verbose_name="합계금액")  # 계산: 단가 * 수량

    def save(self, *args, **kwargs):
        self.total_price = self.unit_price * self.quantity
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.order.order_lot} - {self.injection}"
# Create your models here.
