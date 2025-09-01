from django.db import models

# Create your models here.
class RackMaster(models.Model):
    rack_master_id = models.CharField(max_length=20, unique=True)  # 자동 생성
    product_nm = models.CharField(max_length=100)
    product_no = models.CharField(max_length=100)
    make_comp = models.CharField(max_length=100)
    con_num = models.IntegerField()
    max_count = models.IntegerField()
    use_yn = models.CharField(max_length=1, choices=[('Y', '사용'), ('N', '미사용')])
    dlt_yn = models.CharField(max_length=1, choices=[('N', '정상'), ('Y', '삭제')])
    image = models.ImageField(upload_to='rack/images/', blank=True, null=True)  # ✅ 이미지 필드 추가
    create_date = models.DateTimeField(auto_now_add=True)
    modify_date = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.rack_master_id
