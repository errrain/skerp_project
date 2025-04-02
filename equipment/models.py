
import uuid
from django.db import models
from django.utils import timezone
from vendor.models import Vendor

def equipment_image_upload_path(instance, filename):
    ext = filename.split('.')[-1]
    filename = f"{uuid.uuid4().hex}.{ext}"
    return f"equipment/{filename}"

class Equipment(models.Model):
    name = models.CharField("설비명", max_length=100)
    spec = models.CharField("설비규격", max_length=200, blank=True)
    purchase_date = models.DateField("구입일자", default=timezone.now)
    vendor = models.ForeignKey(Vendor, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="구입처")
    description = models.TextField("설비설명", blank=True)
    image = models.ImageField("설비사진", upload_to=equipment_image_upload_path, blank=True, null=True)
    equipment_code = models.CharField("설비코드", max_length=20, editable=False, unique=True, blank=True)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.equipment_code:
            self.equipment_code = f"SK-M-{self.pk}"
            super().save(update_fields=["equipment_code"])

    def __str__(self):
        return f"{self.equipment_code or '미지정'} - {self.name}"

class EquipmentHistory(models.Model):
    equipment = models.ForeignKey(Equipment, on_delete=models.CASCADE, related_name='histories', verbose_name="설비")
    content = models.CharField("이력내용", max_length=200)
    created_by = models.CharField("작성자", max_length=50)
    created_at = models.DateTimeField("작성일시", auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.created_at.strftime('%Y-%m-%d')}] {self.content}"
