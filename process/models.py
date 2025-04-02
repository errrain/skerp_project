
from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User

def process_file_upload_path(instance, filename):
    return f'process/{instance.process.id}/{filename}'

class Process(models.Model):
    name = models.CharField("공정명", max_length=100)
    description = models.TextField("공정설명", blank=True)

    def __str__(self):
        return self.name

class ProcessFile(models.Model):
    process = models.ForeignKey(Process, on_delete=models.CASCADE, related_name='files', verbose_name="공정")
    file = models.FileField("작업표준서 파일", upload_to=process_file_upload_path)
    note = models.CharField("비고", max_length=200, blank=True)
    created_by = models.CharField("등록자", max_length=50)
    created_at = models.DateTimeField("등록일시", default=timezone.now)

    class Meta:
        ordering = ['-created_at']  # 가장 최근 파일이 위로

    def __str__(self):
        return f"{self.process.name} - {self.file.name}"