import uuid

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models

folder_validator = RegexValidator(r"\A[A-Za-z0-9][A-Za-z0-9_-]{0,79}\Z", "Nur Buchstaben, Ziffern, - und _.")


class Company(models.Model):
    name = models.CharField(max_length=160)
    folder = models.CharField(max_length=80, unique=True, validators=[folder_validator])
    legal_name = models.CharField(max_length=200, blank=True)
    tax_id = models.CharField(max_length=80, blank=True)
    address = models.TextField(blank=True)
    recipients = models.JSONField(default=list, blank=True)
    allow_open_issues = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Membership(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    can_read = models.BooleanField(default=True)
    can_process = models.BooleanField(default=True)
    can_send = models.BooleanField(default=False)
    can_admin = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "company"], name="unique_membership")]


class AccessToken(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(max_length=120)
    digest = models.CharField(max_length=64, unique=True)
    prefix = models.CharField(max_length=12)
    companies = models.ManyToManyField(Company)
    scopes = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked = models.BooleanField(default=False)


class Account(models.Model):
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=10, choices=[("bank", "Bankkonto"), ("depot", "Depot")])
    identifier = models.CharField(max_length=100, blank=True)


class Category(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["company", "name"], name="unique_category")]


class Mailbox(models.Model):
    company = models.OneToOneField(Company, on_delete=models.CASCADE)
    imap_host = models.CharField(max_length=255, blank=True)
    imap_port = models.PositiveIntegerField(default=993)
    imap_tls = models.BooleanField(default=True)
    imap_user = models.CharField(max_length=255, blank=True)
    imap_password = models.TextField(blank=True)  # encrypted by the settings service
    imap_folder = models.CharField(max_length=200, default="INBOX")
    import_since = models.DateField(null=True, blank=True)
    enabled = models.BooleanField(default=False)
    aliases = models.JSONField(default=list, blank=True)
    uidvalidity = models.CharField(max_length=80, blank=True)
    last_uid = models.PositiveBigIntegerField(default=0)
    last_scan_at = models.DateTimeField(null=True, blank=True)
    smtp_host = models.CharField(max_length=255, blank=True)
    smtp_port = models.PositiveIntegerField(default=587)
    smtp_user = models.CharField(max_length=255, blank=True)
    smtp_password = models.TextField(blank=True)
    smtp_security = models.CharField(max_length=10, default="starttls", choices=[("none", "Keine"), ("starttls", "STARTTLS"), ("ssl", "TLS")])
    sender = models.EmailField(blank=True)
    reply_to = models.EmailField(blank=True)
    max_message_bytes = models.PositiveIntegerField(default=18 * 1024 * 1024)
    subject_template = models.CharField(max_length=200, default="Unterlagen {company} – {period} – Paket {version}")
    body_template = models.TextField(default="Guten Tag,\n\nanbei die Unterlagen für {company}, {period}.\n{notes}\n")


KINDS = [
    ("incoming_invoice", "Eingangsrechnung"), ("incoming_credit", "Eingangsgutschrift"),
    ("receipt", "Sonstiger Beleg"), ("outgoing_invoice", "Ausgangsrechnung"),
    ("outgoing_cancellation", "Ausgangsstorno"), ("bank_pdf", "Kontoauszug PDF"),
    ("bank_camt", "Kontoauszug CAMT"), ("security_pdf", "Wertpapierunterlage"),
]


class Document(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(Company, null=True, blank=True, on_delete=models.PROTECT)
    inbox_owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    original_name = models.CharField(max_length=255)
    original_path = models.CharField(max_length=400)
    filed_path = models.CharField(max_length=400, blank=True)
    sha256 = models.CharField(max_length=64, db_index=True)
    size = models.PositiveBigIntegerField()
    media_type = models.CharField(max_length=80)
    kind = models.CharField(max_length=30, choices=KINDS, blank=True)
    period = models.CharField(max_length=7, blank=True, db_index=True)
    account = models.ForeignKey(Account, null=True, blank=True, on_delete=models.PROTECT)
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.PROTECT)
    metadata = models.JSONField(default=dict)
    issues = models.JSONField(default=list)
    status = models.CharField(max_length=20, default="new", choices=[("new", "Neu"), ("review", "Prüfen"), ("ready", "Geprüft")])
    version = models.PositiveIntegerField(default=1)
    parser_result = models.JSONField(default=dict)
    parser_error = models.TextField(blank=True)
    related = models.ManyToManyField("self", blank=True)
    duplicate_of = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["company", "period", "status"])]


class Revision(models.Model):
    document = models.ForeignKey(Document, on_delete=models.PROTECT, related_name="revisions")
    version = models.PositiveIntegerField()
    base_version = models.PositiveIntegerField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    source = models.CharField(max_length=100)
    snapshot = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["document", "version"], name="unique_document_revision")]


class FileOperation(models.Model):
    document = models.ForeignKey(Document, on_delete=models.PROTECT)
    version = models.PositiveIntegerField()
    old_path = models.CharField(max_length=400, blank=True)
    new_path = models.CharField(max_length=400)
    status = models.CharField(max_length=20, default="pending")
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class ImportSource(models.Model):
    document = models.ForeignKey(Document, null=True, blank=True, on_delete=models.PROTECT, related_name="sources")
    mailbox = models.ForeignKey(Mailbox, null=True, on_delete=models.PROTECT)
    identity = models.CharField(max_length=64, unique=True)
    stable_identity = models.CharField(max_length=64, db_index=True)
    provenance = models.JSONField(default=dict)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Job(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    kind = models.CharField(max_length=30)
    idempotency_key = models.CharField(max_length=120)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=20, default="queued")
    result = models.JSONField(default=dict)
    error = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)
    heartbeat = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["company", "kind", "idempotency_key"], name="unique_job_key")]


class Package(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    periods = models.JSONField()
    version = models.PositiveIntegerField()
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT)
    snapshot = models.JSONField()
    path = models.CharField(max_length=400)
    sha256 = models.CharField(max_length=64)
    size = models.PositiveBigIntegerField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    idempotency_key = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["company", "version"], name="unique_package_version"),
                       models.UniqueConstraint(fields=["company", "idempotency_key"], name="unique_package_key")]


class PackageItem(models.Model):
    package = models.ForeignKey(Package, on_delete=models.PROTECT, related_name="items")
    document = models.ForeignKey(Document, on_delete=models.PROTECT)
    revision = models.PositiveIntegerField()
    archive_path = models.CharField(max_length=400)
    sha256 = models.CharField(max_length=64)
    metadata = models.JSONField()


class Dispatch(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    package = models.ForeignKey(Package, on_delete=models.PROTECT, related_name="dispatches")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    idempotency_key = models.CharField(max_length=120)
    recipients = models.JSONField()
    status = models.CharField(max_length=30, default="queued")
    resend_of = models.ForeignKey("self", null=True, on_delete=models.PROTECT)
    parts = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["package", "idempotency_key"], name="unique_dispatch_key")]


class SendAttempt(models.Model):
    dispatch = models.ForeignKey(Dispatch, on_delete=models.PROTECT, related_name="attempts")
    part = models.PositiveIntegerField()
    message_id = models.CharField(max_length=255, unique=True)
    status = models.CharField(max_length=30, default="prepared")
    detail = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)


class UploadTicket(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    company = models.ForeignKey(Company, null=True, on_delete=models.PROTECT)
    filename = models.CharField(max_length=255)
    expected_size = models.PositiveBigIntegerField()
    expected_sha256 = models.CharField(max_length=64)
    uploaded = models.BooleanField(default=False)
    document = models.ForeignKey(Document, null=True, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)


class ProcessingClaim(models.Model):
    document = models.OneToOneField(Document, on_delete=models.CASCADE)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    run_id = models.CharField(max_length=120)
    base_version = models.PositiveIntegerField()
    expires_at = models.DateTimeField()


class IdempotencyRecord(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    operation = models.CharField(max_length=100)
    key = models.CharField(max_length=120)
    request_hash = models.CharField(max_length=64)
    result = models.JSONField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["actor", "operation", "key"], name="unique_idempotency")]
