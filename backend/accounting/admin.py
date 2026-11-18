from django.contrib import admin

from . import models


@admin.register(models.Mailbox)
class MailboxAdmin(admin.ModelAdmin):
    exclude = ["imap_password", "smtp_password"]
    list_display = ["company", "imap_host", "enabled", "last_scan_at"]


@admin.register(models.AccessToken)
class TokenAdmin(admin.ModelAdmin):
    exclude = ["digest"]
    readonly_fields = ["user", "name", "prefix", "scopes", "expires_at"]

    def has_add_permission(self, request):
        return False


# Snapshots are intentionally read-only, including through Django Admin.
class ImmutableAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


for model in (models.Package, models.PackageItem, models.Revision, models.ImportSource, models.SendAttempt, models.Document, models.FileOperation):
    admin.site.register(model, ImmutableAdmin)
for model in (models.Company, models.Membership, models.Account, models.Category):
    admin.site.register(model)
admin.site.register(models.Job, ImmutableAdmin)
admin.site.register(models.Dispatch, ImmutableAdmin)
admin.site.site_header = "Lazy Accountant · Administration"
