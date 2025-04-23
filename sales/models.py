# sales/models.py

from django.db import models
from django.utils import timezone
from vendor.models import Vendor
from product.models import Product

USE_YN_CHOICES = [('Y', '사용'), ('N', '미사용')]
DELETE_YN_CHOICES = [('Y', '삭제'), ('N', '정상')]


class CustomerOrder(models.Model):
    customer = models.ForeignKey(Vendor, on_delete=models.CASCADE, verbose_name='고객사')
    order_date = models.DateField(auto_now_add=True, verbose_name='수주일자')
    memo = models.TextField("비고", blank=True, null=True)

    # 공통 관리 필드
    use_yn = models.CharField("사용여부", max_length=1, choices=USE_YN_CHOICES, default='Y')
    delete_yn = models.CharField("삭제여부", max_length=1, choices=DELETE_YN_CHOICES, default='N')
    created_dt = models.DateTimeField("생성일시", auto_now_add=True)
    updated_dt = models.DateTimeField("수정일시", auto_now=True)
    created_by = models.CharField("생성자", max_length=50, blank=True, null=True)
    updated_by = models.CharField("수정자", max_length=50, blank=True, null=True)

    def __str__(self):
        return f"[{self.customer.name}] 수주 ({self.order_date})"


class CustomerOrderItem(models.Model):
    order = models.ForeignKey(CustomerOrder, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, verbose_name='제품')
    quantity = models.PositiveIntegerField("수량")
    delivery_date = models.DateField("출하예정일")
    invoice_number = models.CharField("Invoice No", max_length=100, blank=True, null=True)  # ✅ 추가

    # 출하 후 갱신되는 정보
    shipped_date = models.DateField("출고일", null=True, blank=True)
    status = models.CharField(
        "출하상태",
        max_length=20,
        choices=[
            ('등록', '등록'),
            ('지연', '지연'),
            ('부분출고', '부분출고'),
            ('출고', '출고'),
        ],
        default='등록'
    )

    # 단가 정보 (수주 시점 가격)
    unit_price = models.PositiveIntegerField("단가", default=0)
    total_price = models.PositiveIntegerField("합계금액", default=0)

    # 공통 관리 필드
    use_yn = models.CharField("사용여부", max_length=1, choices=USE_YN_CHOICES, default='Y')
    delete_yn = models.CharField("삭제여부", max_length=1, choices=DELETE_YN_CHOICES, default='N')
    created_dt = models.DateTimeField("생성일시", auto_now_add=True)
    updated_dt = models.DateTimeField("수정일시", auto_now=True)
    created_by = models.CharField("생성자", max_length=50, blank=True, null=True)
    updated_by = models.CharField("수정자", max_length=50, blank=True, null=True)

    def is_delayed(self):
        return self.shipped_date is None and self.delivery_date < timezone.now().date()

    def __str__(self):
        return f"{self.product.name} / {self.quantity}개 / {self.status}"
