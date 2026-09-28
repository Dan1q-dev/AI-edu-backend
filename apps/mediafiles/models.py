from django.conf import settings
from django.db import models

class MediaFile(models.Model):
    file = models.ImageField(upload_to='lessons/%Y/%m/')
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=50)
    size = models.PositiveIntegerField()
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
