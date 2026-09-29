import secrets
from django.utils.text import slugify
from django.db import models
from django.db.models import PROTECT
from django.core.exceptions import ValidationError

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
    is_active = models.BooleanField(default=True)
    is_system = models.BooleanField(default=False, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    def delete(self, *args, **kwargs):
        if self.is_system:
            raise ValidationError('Базовую траекторию нельзя удалить')
        return super().delete(*args, **kwargs)
    def __str__(self): return self.title

class Course(ShortIdModel):
    learning_track = models.ForeignKey(LearningTrack, null=True, blank=True, on_delete=PROTECT, related_name='courses')
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True, allow_unicode=True)
    description = models.TextField(blank=True)
    cover = models.ForeignKey('mediafiles.MediaFile', null=True, blank=True, on_delete=models.SET_NULL)
    position = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ['position', 'id']
    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title, allow_unicode=True)[:200] or 'course'
            candidate = base
            suffix = 2
            while Course.objects.exclude(pk=self.pk).filter(slug=candidate).exists():
                candidate = f'{base[:210 - len(str(suffix))]}-{suffix}'
                suffix += 1
            self.slug = candidate
        super().save(*args, **kwargs)
    def __str__(self): return self.title

class Module(ShortIdModel):
    course = models.ForeignKey(Course, on_delete=PROTECT, related_name='modules')
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
