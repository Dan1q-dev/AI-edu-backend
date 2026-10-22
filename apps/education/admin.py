from django.contrib import admin
from django.utils import timezone
from .models import Certificate


@admin.register(Certificate)
class CertificateAdmin(admin.ModelAdmin):
    list_display = ('token', 'learner_name', 'course_title', 'hours', 'issued_at', 'revoked_at')
    search_fields = ('learner_name', 'course_title', 'token')
    readonly_fields = ('token', 'user', 'course', 'learner_name', 'course_title', 'track_title', 'hours', 'completed_at', 'issued_at', 'revoked_at')
    actions = ['revoke']

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description='Аннулировать выбранные сертификаты')
    def revoke(self, request, queryset):
        queryset.filter(revoked_at__isnull=True).update(revoked_at=timezone.now())
