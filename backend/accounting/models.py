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
    smtp_security = models.CharField(
        max_length=10,
        default="starttls",
        choices=[("none", "Keine"), ("starttls", "STARTTLS"), ("ssl", "TLS")],
    )
    sender = models.EmailField(blank=True)
    reply_to = models.EmailField(blank=True)
    max_message_bytes = models.PositiveIntegerField(default=18 * 1024 * 1024)
    subject_template = models.CharField(
        max_length=200, default="Unterlagen {company} – {period} – Paket {version}"
    )
    body_template = models.TextField(
        default="Guten Tag,\n\nanbei die Unterlagen für {company}, {period}.\n{notes}\n"
    )


KINDS = [
    ("incoming_invoice", "Eingangsrechnung"),
    ("incoming_credit", "Eingangsgutschrift"),
    ("receipt", "Sonstiger Beleg"),
    ("outgoing_invoice", "Ausgangsrechnung"),
    ("outgoing_cancellation", "Ausgangsstorno"),
    ("bank_pdf", "Kontoauszug PDF"),
    ("bank_camt", "Kontoauszug CAMT"),
    ("security_pdf", "Wertpapierunterlage"),
]


class Document(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(Company, null=True, blank=True, on_delete=models.PROTECT)
    inbox_owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    original_name = models.CharField(max_length=255)
    handover_name = models.CharField(max_length=255, blank=True)
    name_source = models.CharField(
        max_length=10,
        blank=True,
        choices=[("generated", "Generiert"), ("manual", "Manuell"), ("fallback", "Originalname")],
    )
    original_path = models.CharField(max_length=400)
    filed_path = models.CharField(max_length=400, blank=True)
    sha256 = models.CharField(max_length=64, db_index=True)
    size = models.PositiveBigIntegerField()
    media_type = models.CharField(max_length=80)
    security_status = models.CharField(
        max_length=10,
        default="pending",
        db_index=True,
        choices=[(s, s) for s in ("pending", "scanning", "clean", "infected", "error")],
    )
    security_error = models.CharField(max_length=500, blank=True)
    scanned_sha256 = models.CharField(max_length=64, blank=True)
    scanned_at = models.DateTimeField(null=True)
    quarantine_path = models.CharField(max_length=400, blank=True)
    scan_attempts = models.PositiveIntegerField(default=0)
    scan_due_at = models.DateTimeField(null=True)
    kind = models.CharField(max_length=30, choices=KINDS, blank=True)
    period = models.CharField(max_length=7, blank=True, db_index=True)
    account = models.ForeignKey(Account, null=True, blank=True, on_delete=models.PROTECT)
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.PROTECT)
    metadata = models.JSONField(default=dict)
    issues = models.JSONField(default=list)
    status = models.CharField(
        max_length=20, default="new", choices=[("new", "Neu"), ("review", "Prüfen"), ("ready", "Geprüft")]
    )
    is_excluded = models.BooleanField(default=False, db_index=True)
    exclusion_reason = models.CharField(max_length=1000, blank=True)
    excluded_at = models.DateTimeField(null=True, blank=True)
    excluded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="excluded_documents",
    )
    version = models.PositiveIntegerField(default=1)
    parser_result = models.JSONField(default=dict)
    parser_error = models.TextField(blank=True)
    # Each reference belongs to the revision of its source document. Symmetric
    # writes would silently change another document without bumping its version.
    related = models.ManyToManyField("self", blank=True, symmetrical=False, related_name="referenced_by")
    duplicate_of = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["company", "period", "status"])]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(is_excluded=True, excluded_at__isnull=False, excluded_by__isnull=False)
                    & ~models.Q(exclusion_reason="")
                )
                | models.Q(
                    is_excluded=False,
                    excluded_at__isnull=True,
                    excluded_by__isnull=True,
                    exclusion_reason="",
                ),
                name="document_exclusion_details",
            )
        ]


class ScanAttempt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(Document, on_delete=models.PROTECT, related_name="scans")
    sha256 = models.CharField(max_length=64)
    engine = models.CharField(max_length=200, blank=True)
    result = models.CharField(max_length=10, default="scanning")
    signature = models.CharField(max_length=200, blank=True)
    reason = models.CharField(max_length=500, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True)


class Revision(models.Model):
    document = models.ForeignKey(Document, on_delete=models.PROTECT, related_name="revisions")
    version = models.PositiveIntegerField()
    base_version = models.PositiveIntegerField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    source = models.CharField(max_length=100)
    reason = models.CharField(max_length=1000, blank=True)
    snapshot = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["document", "version"], name="unique_document_revision")
        ]


class FileOperation(models.Model):
    document = models.ForeignKey(Document, on_delete=models.PROTECT)
    version = models.PositiveIntegerField()
    old_path = models.CharField(max_length=400, blank=True)
    new_path = models.CharField(max_length=400)
    status = models.CharField(max_length=20, default="pending")
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class ImportSource(models.Model):
    document = models.ForeignKey(
        Document, null=True, blank=True, on_delete=models.PROTECT, related_name="sources"
    )
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
        constraints = [
            models.UniqueConstraint(fields=["company", "kind", "idempotency_key"], name="unique_job_key")
        ]


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
        constraints = [
            models.UniqueConstraint(fields=["company", "version"], name="unique_package_version"),
            models.UniqueConstraint(fields=["company", "idempotency_key"], name="unique_package_key"),
        ]


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
        constraints = [
            models.UniqueConstraint(fields=["package", "idempotency_key"], name="unique_dispatch_key")
        ]


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


class BankTransaction(models.Model):
    """Canonical booked movement; originals live in BankTransactionSource."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    account = models.ForeignKey(Account, on_delete=models.PROTECT)
    identity = models.CharField(max_length=64)
    amount = models.DecimalField(max_digits=20, decimal_places=6)
    currency = models.CharField(max_length=3)
    direction = models.CharField(max_length=4)
    booking_date = models.DateField(null=True)
    value_date = models.DateField(null=True)
    bank_reference = models.CharField(max_length=300)
    party_name = models.CharField(max_length=300, blank=True)
    party_iban = models.CharField(max_length=100, blank=True)
    remittance = models.TextField(blank=True)
    booked = models.BooleanField(default=False)
    reversal = models.BooleanField(default=False)
    references = models.JSONField(default=dict)
    review_points = models.JSONField(default=list)
    identity_review_points = models.JSONField(default=list)
    merged_into = models.ForeignKey(
        "self", null=True, on_delete=models.PROTECT, related_name="merged_duplicates"
    )
    reversal_of = models.OneToOneField(
        "self", null=True, on_delete=models.PROTECT, related_name="bank_reversal"
    )
    reversal_applied_at = models.DateTimeField(null=True)
    reversal_actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="bank_reversals"
    )
    issues = models.JSONField(default=list)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["company", "account", "identity"], name="unique_bank_identity"),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="positive_bank_amount"),
            models.CheckConstraint(
                condition=~models.Q(merged_into=models.F("id")), name="bank_identity_not_self"
            ),
        ]


class BankIdentityResolution(models.Model):
    """Explicit, source-preserving identity link; never moves a financial allocation."""

    duplicate = models.OneToOneField(
        BankTransaction, on_delete=models.PROTECT, related_name="identity_resolution"
    )
    canonical = models.ForeignKey(
        BankTransaction, on_delete=models.PROTECT, related_name="identity_resolutions"
    )
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    reason = models.CharField(max_length=1000)
    evidence = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    disputed_at = models.DateTimeField(null=True)
    disputed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="disputed_bank_identities"
    )
    dispute_reason = models.CharField(max_length=1000, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(duplicate=models.F("canonical")), name="identity_resolution_not_self"
            )
        ]


class BankTransactionSource(models.Model):
    transaction = models.ForeignKey(BankTransaction, on_delete=models.PROTECT, related_name="sources")
    document = models.ForeignKey(Document, on_delete=models.PROTECT)
    document_version = models.PositiveIntegerField()
    locator = models.CharField(max_length=160)
    parser_version = models.CharField(max_length=40, default="reconciliation-v1")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["document", "locator"], name="unique_bank_source"),
        ]


class VerifiedBankParty(models.Model):
    """Explicitly trusted party/account pair, never learned from invoice text."""

    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    name = models.CharField(max_length=300)
    iban = models.CharField(max_length=100)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    reason = models.CharField(max_length=1000)
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="revoked_bank_parties"
    )
    revocation_reason = models.CharField(max_length=1000, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["company", "name", "iban"],
                condition=models.Q(revoked_at__isnull=True),
                name="unique_verified_bank_party",
            ),
        ]


class PaymentAllocation(models.Model):
    """Bank-only initial adapter for imported ER/AR; not a second Invoice model."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    transaction = models.ForeignKey(BankTransaction, on_delete=models.PROTECT, related_name="allocations")
    document = models.ForeignKey(Document, on_delete=models.PROTECT, related_name="payment_allocations")
    amount = models.DecimalField(max_digits=20, decimal_places=6)
    decision = models.CharField(max_length=30)
    evidence = models.JSONField(default=dict)
    reason = models.CharField(max_length=1000)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    reversed_at = models.DateTimeField(null=True)
    reversed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="reversed_allocations"
    )
    reversal_reason = models.CharField(max_length=1000, blank=True)
    reversed_by_bank_transaction = models.ForeignKey(
        BankTransaction, null=True, on_delete=models.PROTECT, related_name="reversed_allocations"
    )

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(amount__gt=0), name="positive_allocation")]


class BankAutomationPolicy(models.Model):
    """Company preference; never authorizes transfers or bypasses matching guards."""

    company = models.OneToOneField(Company, on_delete=models.PROTECT)
    enabled = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)


class BankMonthCoverage(models.Model):
    account = models.ForeignKey(Account, on_delete=models.PROTECT)
    period = models.CharField(max_length=7)
    state = models.CharField(
        max_length=12,
        choices=[("confirmed", "Bestätigt"), ("disputed", "Widerspruch"), ("unknown", "Ungeklärt")],
    )
    version = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["account", "period"], name="unique_bank_month_coverage")
        ]


class BankCoverageSource(models.Model):
    coverage = models.ForeignKey(BankMonthCoverage, on_delete=models.PROTECT, related_name="sources")
    document = models.ForeignKey(Document, on_delete=models.PROTECT)
    document_version = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)

    # Evidence for the current declaration; earlier declarations remain in BankControlEvent.
    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["coverage", "document"], name="unique_bank_coverage_source")
        ]


class BankControlEvent(models.Model):
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    operation = models.CharField(max_length=30)
    account = models.ForeignKey(Account, null=True, on_delete=models.PROTECT)
    period = models.CharField(max_length=7, blank=True)
    version = models.PositiveIntegerField()
    reason = models.CharField(max_length=1000)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)


class IdempotencyRecord(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    operation = models.CharField(max_length=100)
    key = models.CharField(max_length=120)
    request_hash = models.CharField(max_length=64)
    result = models.JSONField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["actor", "operation", "key"], name="unique_idempotency")
        ]
