from django.db import models

class LessonBlock(models.Model):
    class Type(models.TextChoices):
        TEXT = 'TEXT'
        IMAGE = 'IMAGE'
    lesson = models.ForeignKey('education.Lesson', on_delete=models.PROTECT, related_name='blocks')
    type = models.CharField(max_length=10, choices=Type.choices)
    position = models.PositiveIntegerField()
    content = models.TextField(blank=True)
    media = models.ForeignKey('mediafiles.MediaFile', null=True, blank=True, on_delete=models.PROTECT)
    config = models.JSONField(default=dict, blank=True)
    class Meta:
        ordering = ['position', 'id']
        constraints = [models.UniqueConstraint(fields=['lesson', 'position'], name='unique_block_position')]
