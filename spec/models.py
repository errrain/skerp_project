import uuid
from django.db import models
from django.utils import timezone

def spec_image_upload_path(instance, filename):
    ext = filename.split('.')[-1]
    filename = f"{uuid.uuid4().hex}.{ext}"
    return f"spec/{filename}"

class Spec(models.Model):
    name = models.CharField("사양명", max_length=100)
    description = models.TextField("설명", blank=True)
    image = models.ImageField("COLOR SAMPLE", upload_to=spec_image_upload_path, blank=True, null=True)
    created_at = models.DateTimeField("등록일시", default=timezone.now)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name
