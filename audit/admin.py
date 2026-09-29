from django.contrib import admin

from audit.models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("action", "organization", "user", "target_type", "ip", "created_at")
    list_filter = ("action",)
    search_fields = ("action", "organization__name", "user__email")
    readonly_fields = [f.name for f in AuditEvent._meta.fields]
