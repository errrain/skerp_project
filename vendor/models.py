from django.db import models

class Vendor(models.Model):
    VENDOR_TYPE_CHOICES = [
        ('corporate', '법인'),
        ('personal', '개인'),
    ]

    TRANSACTION_TYPE_CHOICES = [
        ('buy', '매입'),
        ('sell', '매출'),
        ('both', '매입매출 병행'),
    ]

    OUTSOURCING_TYPE_CHOICES = [
        ('CL', '거래처'),      # Client의 약자. 일반적인 외부 고객사 의미
        ('PT', '협력사'),      # Partner의 약자. 공식 협력관계 강조
        ('OD', '외주처'),      # OutSourcing을 줄인 약자
        ('CT', '도급사'),      # Contractor 의미의 약자. 계약 기반 작업 위임
    ]

    STATUS_CHOICES = [
        ('active', '사용'),
        ('inactive', '미사용'),
    ]

    vendor_type = models.CharField('구분', max_length=20, choices=VENDOR_TYPE_CHOICES)
    name = models.CharField('기업명', max_length=100)
    biz_number = models.CharField('사업자번호', max_length=20)
    transaction_type = models.CharField('거래구분', max_length=20, choices=TRANSACTION_TYPE_CHOICES)
    outsourcing_type = models.CharField('외주구분', max_length=2, choices=OUTSOURCING_TYPE_CHOICES)
    ceo_name = models.CharField('대표자 이름', max_length=50, blank=True, null=True)
    biz_type = models.CharField('업태', max_length=100, blank=True, null=True)
    biz_item = models.CharField('업종', max_length=100, blank=True, null=True)
    phone = models.CharField('대표 전화', max_length=20, blank=True, null=True)
    fax = models.CharField('대표 팩스', max_length=20, blank=True, null=True)
    email = models.EmailField('대표 이메일', blank=True, null=True)
    manager_name = models.CharField('담당자명', max_length=50, blank=True, null=True)
    contact_phone = models.CharField('담당자 전화번호', max_length=20, blank=True, null=True)
    status = models.CharField('사용여부', max_length=10, choices=STATUS_CHOICES)

    # ✅ 추가 필드 (2025. 08. 07)
    can_login = models.BooleanField('로그인허용', default=False)
    address = models.CharField('주소', max_length=200, blank=True, null=True)

    def __str__(self):
        return self.name
