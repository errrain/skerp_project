# mastercode/models.py

from django.db import models

class CodeGroup(models.Model):
    group_code = models.CharField(max_length=50, unique=True, verbose_name="그룹코드")
    group_name = models.CharField(max_length=100, verbose_name="그룹명")

    def __str__(self):
        return self.group_name

    class Meta:
        verbose_name = "코드그룹"
        verbose_name_plural = "코드그룹 목록"
        ordering = ['group_code']


class CodeDetail(models.Model):
    group = models.ForeignKey(CodeGroup, on_delete=models.CASCADE, verbose_name="코드그룹")
    code = models.CharField(max_length=50, verbose_name="코드")
    name = models.CharField(max_length=100, verbose_name="코드명")
    sort_order = models.PositiveIntegerField(default=1, verbose_name="정렬순서")
    is_active = models.BooleanField(default=True, verbose_name="사용여부")

    def __str__(self):
        return f"[{self.group.group_code}] {self.name}"

    class Meta:
        verbose_name = "코드상세"
        verbose_name_plural = "코드상세 목록"
        unique_together = ('group', 'code')
        ordering = ['group__group_code', 'sort_order']
