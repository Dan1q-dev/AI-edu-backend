from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils import timezone


class PracticeDefinition(models.Model):
    # Legacy fields are retained for lossless upgrades, not used by the engine.
    lesson = models.ForeignKey('education.Lesson', null=True, blank=True, on_delete=models.PROTECT, related_name='practices')
    kind = models.CharField(max_length=100, blank=True)
    version = models.PositiveIntegerField(default=1)
    config = models.JSONField(default=dict)
    is_enabled = models.BooleanField(default=False)
    practice_type = models.CharField(max_length=100, blank=True)
    title = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(default=timezone.now)

    def save(self, *args, **kwargs):
        if self.pk and self.versions.exists():
            original = type(self).objects.get(pk=self.pk)
            if original.practice_type != self.practice_type:
                raise ValidationError('Practice type cannot change after version creation')
        self.updated_at = timezone.now()
        return super().save(*args, **kwargs)


class VersionQuerySet(models.QuerySet):
    def update(self, **kwargs):
        if self.filter(status='PUBLISHED').exists():
            raise ValidationError('Published practice versions are immutable')
        return super().update(**kwargs)

    def delete(self):
        if self.filter(status='PUBLISHED').exists():
            raise ValidationError('Published practice versions are immutable')
        return super().delete()


class PracticeVersion(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'DRAFT'
        PUBLISHED = 'PUBLISHED'

    practice_definition = models.ForeignKey(PracticeDefinition, on_delete=models.CASCADE, related_name='versions')
    version_number = models.PositiveIntegerField()
    plugin_version = models.CharField(max_length=30, default='1.0.0')
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    config = models.JSONField(default=dict)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    published_at = models.DateTimeField(null=True, blank=True)
    objects = VersionQuerySet.as_manager()

    class Meta:
        ordering = ['version_number']
        constraints = [models.UniqueConstraint(fields=['practice_definition', 'version_number'], name='unique_practice_version')]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk, status='PUBLISHED').exists():
            raise ValidationError('Published practice versions are immutable; create a new draft')
        from .registry import registry
        registry.get(self.practice_definition.practice_type, self.plugin_version).validate_config(self.config)
        if self.status == self.Status.PUBLISHED:
            from django.utils import timezone
            self.published_at = self.published_at or timezone.now()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if type(self).objects.filter(pk=self.pk, status='PUBLISHED').exists():
            raise ValidationError('Published practice versions are immutable')
        return super().delete(*args, **kwargs)


class CriterionQuerySet(models.QuerySet):
    def bulk_create(self, objs, **kwargs):
        objs = list(objs)
        if PracticeVersion.objects.filter(pk__in=[row.practice_version_id for row in objs], status='PUBLISHED').exists():
            raise ValidationError('Published criteria are immutable')
        return super().bulk_create(objs, **kwargs)

    def update(self, **kwargs):
        self.ensure_mutable()
        return super().update(**kwargs)

    def delete(self):
        self.ensure_mutable()
        return super().delete()

    def ensure_mutable(self):
        if self.filter(practice_version__status='PUBLISHED').exists():
            raise ValidationError('Published criteria are immutable')


class PracticeCriterion(models.Model):
    practice_version = models.ForeignKey(PracticeVersion, on_delete=models.CASCADE, related_name='criteria')
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    position = models.PositiveIntegerField()
    is_required = models.BooleanField(default=True)
    objects = CriterionQuerySet.as_manager()

    class Meta:
        ordering = ['position', 'id']
        constraints = [models.UniqueConstraint(fields=['practice_version', 'position'], name='unique_practice_criterion_position')]

    def save(self, *args, **kwargs):
        if (PracticeVersion.objects.filter(pk=self.practice_version_id, status='PUBLISHED').exists() or
                self.pk and type(self).objects.filter(pk=self.pk, practice_version__status='PUBLISHED').exists()):
            raise ValidationError('Published criteria are immutable')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if PracticeVersion.objects.filter(pk=self.practice_version_id, status='PUBLISHED').exists():
            raise ValidationError('Published criteria are immutable')
        return super().delete(*args, **kwargs)


class PracticeResult(models.Model):
    class Source(models.TextChoices):
        SELF_ASSESSMENT = 'SELF_ASSESSMENT'
        AUTO_GRADING = 'AUTO_GRADING'
        AI_GRADING = 'AI_GRADING'
        TEACHER = 'TEACHER'

    submission = models.OneToOneField('education.PracticeSubmission', on_delete=models.CASCADE, related_name='result')
    self_assessment_score = models.FloatField(null=True, blank=True)
    automatic_score = models.FloatField(null=True, blank=True)
    teacher_score = models.FloatField(null=True, blank=True)
    effective_score = models.FloatField(validators=[MinValueValidator(0), MaxValueValidator(1)])
    grading_source = models.CharField(max_length=20, choices=Source.choices)
    psi_value = models.FloatField(validators=[MinValueValidator(0), MaxValueValidator(1)])
    psi_source = models.CharField(max_length=20, choices=Source.choices)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
