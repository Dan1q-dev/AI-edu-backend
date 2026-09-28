from django.db import models

class PracticeDefinition(models.Model):
    lesson = models.ForeignKey('education.Lesson', on_delete=models.PROTECT, related_name='practices')
    kind = models.CharField(max_length=100)
    version = models.PositiveIntegerField(default=1)
    config = models.JSONField(default=dict)
    is_enabled = models.BooleanField(default=False)

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.is_enabled:
            raise ValidationError('Типы практик пока не зарегистрированы')
