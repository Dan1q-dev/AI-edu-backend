import secrets
from django.db import models
from django.db.models import PROTECT

def generate_short_id():
    # token_urlsafe(8) returns 11 chars; truncate to keep public IDs at 10 chars.
    return secrets.token_urlsafe(8)[:10]

class ShortIdModel(models.Model):
    short_id = models.CharField(max_length=10, unique=True, default=generate_short_id, editable=False)

    class Meta:
        abstract = True

class LearningTrack(ShortIdModel):
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    cover = models.ForeignKey('mediafiles.MediaFile', null=True, blank=True, on_delete=models.SET_NULL)
    is_published = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    def __str__(self): return self.title

class Module(ShortIdModel):
    track = models.ForeignKey(LearningTrack, on_delete=PROTECT, related_name='modules')
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    position = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(default=False)
    class Meta:
        ordering = ['position', 'id']
    def __str__(self): return self.title

class Lesson(ShortIdModel):
    class Status(models.TextChoices):
        DRAFT = 'DRAFT'
        PUBLISHED = 'PUBLISHED'
    module = models.ForeignKey(Module, on_delete=PROTECT, related_name='lessons')
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    position = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ['position', 'id']
    def __str__(self): return self.title
