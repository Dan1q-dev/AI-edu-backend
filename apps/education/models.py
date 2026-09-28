from django.db import models
from django.db.models import PROTECT

class LearningTrack(models.Model):
    title = models.CharField(max_length=200)
    slug = models.SlugField(unique=True, allow_unicode=True)
    description = models.TextField(blank=True)
    cover = models.ForeignKey('mediafiles.MediaFile', null=True, blank=True, on_delete=models.SET_NULL)
    is_published = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    def __str__(self): return self.title

class Module(models.Model):
    track = models.ForeignKey(LearningTrack, on_delete=PROTECT, related_name='modules')
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    position = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(default=False)
    class Meta:
        ordering = ['position', 'id']
    def __str__(self): return self.title

class Lesson(models.Model):
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
