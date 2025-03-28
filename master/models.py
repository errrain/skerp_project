# master/models.py
from django.db import models


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