#process/models.py
from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User  # (지금은 안 쓰지만 기존 코드 유지)


def process_file_upload_path(instance, filename):
    return f'process/{instance.process.id}/{filename}'


class Process(models.Model):
    name = models.CharField("공정명", max_length=100)
    description = models.TextField("공정설명", blank=True)

    # 공정 리스트 정렬용 순번
    display_order = models.PositiveSmallIntegerField(
        "표시순번",
        default=1,
        help_text="공정 목록에서의 표시 순번",
    )

    # 공정별 사용 약품 (ManyToMany + 중간 테이블)
    chemicals = models.ManyToManyField(
        'chemical.Chemical',
        verbose_name="사용 약품",
        blank=True,
        through='ProcessChemical',
        related_name='processes',
    )

    # 공정별 사용 설비 (ManyToMany + 중간 테이블)
    equipments = models.ManyToManyField(
        'equipment.Equipment',
        verbose_name="사용 설비",
        blank=True,
        through='ProcessEquipment',
        related_name='processes',
    )

    class Meta:
        ordering = ['display_order', 'id']
        verbose_name = "공정"
        verbose_name_plural = "공정"

    def __str__(self):
        return self.name


class ProcessFile(models.Model):
    process = models.ForeignKey(
        Process,
        on_delete=models.CASCADE,
        related_name='files',
        verbose_name="공정",
    )
    file = models.FileField("작업표준서 파일", upload_to=process_file_upload_path)
    note = models.CharField("비고", max_length=200, blank=True)
    created_by = models.CharField("등록자", max_length=50)
    created_at = models.DateTimeField("등록일시", default=timezone.now)

    class Meta:
        ordering = ['-created_at']  # 가장 최근 파일이 위로

    def __str__(self):
        return f"{self.process.name} - {self.file.name}"


class ProcessChemical(models.Model):
    """공정별로 사용되는 약품 매핑"""
    process = models.ForeignKey(
        'Process',
        on_delete=models.CASCADE,
        verbose_name="공정",
    )
    chemical = models.ForeignKey(
        'chemical.Chemical',
        on_delete=models.PROTECT,
        verbose_name="약품",
    )
    order = models.PositiveSmallIntegerField("표시순서", default=1)

    class Meta:
        unique_together = ('process', 'chemical')
        ordering = ['process', 'order', 'id']
        verbose_name = "공정별 약품"
        verbose_name_plural = "공정별 약품"

    def __str__(self):
        return f"{self.process.name} - {self.chemical.name}"


class ProcessEquipment(models.Model):
    """공정별로 사용되는 설비 매핑"""
    process = models.ForeignKey(
        'Process',
        on_delete=models.CASCADE,
        verbose_name="공정",
    )
    equipment = models.ForeignKey(
        'equipment.Equipment',
        on_delete=models.PROTECT,
        verbose_name="설비",
    )
    order = models.PositiveSmallIntegerField("표시순서", default=1)

    class Meta:
        unique_together = ('process', 'equipment')
        ordering = ['process', 'order', 'id']
        verbose_name = "공정별 설비"
        verbose_name_plural = "공정별 설비"

    def __str__(self):
        return f"{self.process.name} - {self.equipment.name}"