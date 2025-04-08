from django.db import models

class QualityGroup(models.Model):
    code = models.CharField("검사구분코드", max_length=10, unique=True)
    name = models.CharField("검사구분명", max_length=100)
    use_yn = models.CharField("사용여부", max_length=1, choices=[('Y', '사용'), ('N', '미사용')], default='Y')

    # 공통 필드
    created_dt = models.DateTimeField("생성일시", auto_now_add=True)
    updated_dt = models.DateTimeField("수정일시", auto_now=True)
    created_by = models.CharField("생성자", max_length=50, blank=True, null=True)
    updated_by = models.CharField("수정자", max_length=50, blank=True, null=True)

    def __str__(self):
        return f"{self.name} ({self.code})"


class QualityItem(models.Model):
    group = models.ForeignKey(QualityGroup, on_delete=models.CASCADE, related_name='items')
    code = models.CharField("검사항목코드", max_length=20, unique=True)
    name = models.CharField("검사항목명", max_length=100)
    method = models.TextField("검사방법", blank=True)
    upper_limit = models.DecimalField("허용 상한", max_digits=10, decimal_places=2, null=True, blank=True)
    lower_limit = models.DecimalField("허용 하한", max_digits=10, decimal_places=2, null=True, blank=True)
    use_yn = models.CharField("사용여부", max_length=1, choices=[('Y', '사용'), ('N', '미사용')], default='Y')

    # 공통 필드
    created_dt = models.DateTimeField("생성일시", auto_now_add=True)
    updated_dt = models.DateTimeField("수정일시", auto_now=True)
    created_by = models.CharField("생성자", max_length=50, blank=True, null=True)
    updated_by = models.CharField("수정자", max_length=50, blank=True, null=True)

    def __str__(self):
        return f"{self.name} ({self.code})"
