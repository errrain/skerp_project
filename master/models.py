from django.db import models


# ✅ 서경화학 기업정보
class CompanyInfo(models.Model):
    biz_number = models.CharField('사업자번호', max_length=20)
    name = models.CharField('기업명', max_length=100)
    ceo_name = models.CharField('대표자 이름', max_length=50)
    biz_type = models.CharField('업태', max_length=100)
    biz_item = models.CharField('업종', max_length=100)
    address = models.TextField('주소')
    phone = models.CharField('대표 전화번호', max_length=20)
    fax = models.CharField('대표 팩스번호', max_length=20, blank=True, null=True)
    email = models.EmailField('대표 이메일', blank=True, null=True)
    tax_email = models.EmailField('세금계산서 이메일', blank=True, null=True)

    def __str__(self):
        return self.name


# ✅ 창고정보 모델 (논리적 창고 단위)
class Warehouse(models.Model):
    warehouse_id = models.CharField('창고 ID', max_length=20, unique=True)
    name = models.CharField('창고명', max_length=100)
    description = models.TextField('창고 설명', blank=True, null=True)
    is_active = models.CharField('사용여부', max_length=1, choices=[('Y', '사용'), ('N', '미사용')], default='Y')
    is_deleted = models.CharField('삭제여부', max_length=1, choices=[('N', '정상'), ('Y', '삭제')], default='N')

    def __str__(self):
        return f"{self.name} ({self.warehouse_id})"
