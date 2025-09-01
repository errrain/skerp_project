# injectionorder/models.py
from django.db import models
from django.utils import timezone
from vendor.models import Vendor
from injection.models import Injection  # 사출품 모델

# 표준 상태(고정)
STATUS_CHOICES = [
    ('미입고', '미입고'),
    ('입고대기', '입고대기'),
    ('입고완료', '입고완료'),
    ('반출', '반출'),
]

class InjectionOrder(models.Model):
    order_lot = models.CharField(max_length=20, unique=True, verbose_name="발주 LOT")
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT, verbose_name="발주처")
    order_date = models.DateField(default=timezone.now, verbose_name="발주일")

    # ▼ 신규/보강: 협력사 앱 v1 필수
    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default='미입고',
        db_index=True, verbose_name='상태'
    )
    shipping_registered_at = models.DateTimeField(
        null=True, blank=True, verbose_name='배송등록 시각'
    )
    # 헤더 기본 입고예정일(라인별 expected_date가 있어도, 목록/검색 성능 위해 헤더 기본값 운용)
    due_date = models.DateField(null=True, blank=True, verbose_name='입고 예정일(헤더)')

    # ▼ 기존
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="생성일시")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="수정일시")
    dlt_yn = models.CharField(
        max_length=1, choices=[('N', '정상'), ('Y', '삭제')], default='N', verbose_name='삭제여부'
    )

    class Meta:
        verbose_name = "사출 발주"
        verbose_name_plural = "사출 발주"
        indexes = [
            models.Index(fields=['vendor', 'status'], name='injord_vendor_status_idx'),
            models.Index(fields=['order_date'], name='injord_orderdate_idx'),
        ]

    def __str__(self):
        return self.order_lot

    # -------- 편의 메서드(뷰/템플릿에서 사용) --------
    @property
    def is_actionable_for_vendor(self) -> bool:
        """협력사 화면에서 '배송등록' 가능 여부(미입고/반출만 허용)"""
        return self.status in ('미입고', '반출')

    def mark_shipping_registered(self):
        """배송등록 처리: 미입고/반출 → 입고대기 + 시각 기록"""
        if self.status in ('미입고', '반출'):
            self.status = '입고대기'
            self.shipping_registered_at = timezone.now()
            self.save(update_fields=['status', 'shipping_registered_at', 'updated_at'])


class InjectionOrderItem(models.Model):
    order = models.ForeignKey(
        InjectionOrder, on_delete=models.CASCADE, related_name="items", verbose_name="발주"
    )
    injection = models.ForeignKey(Injection, on_delete=models.PROTECT, verbose_name="사출품")
    quantity = models.PositiveIntegerField(verbose_name="발주 수량")
    expected_date = models.DateField(verbose_name="입고 예정일")
    unit_price = models.PositiveIntegerField(verbose_name="단가")  # 발주 당시 단가
    total_price = models.PositiveIntegerField(verbose_name="합계금액")  # 계산: 단가 * 수량

    class Meta:
        verbose_name = "사출 발주 품목"
        verbose_name_plural = "사출 발주 품목"
        indexes = [
            models.Index(fields=['order'], name='injitem_order_idx'),
            models.Index(fields=['expected_date'], name='injitem_expected_idx'),
        ]

    def save(self, *args, **kwargs):
        self.total_price = (self.unit_price or 0) * (self.quantity or 0)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.order.order_lot} - {self.injection}"
