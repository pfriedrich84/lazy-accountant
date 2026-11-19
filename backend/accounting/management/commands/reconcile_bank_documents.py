"""Explicit, resumable backfill. Default is a rolled-back dry-run, not a scheduler."""

import json

from django.core.management.base import BaseCommand
from django.db import transaction

from accounting.auth import Actor, DomainError
from accounting.models import Document
from accounting.reconciliation import reconcile_document


class Command(BaseCommand):
    help = "Geprüfte CAMT-Dokumente abgleichen; ohne --apply werden alle DB-Änderungen zurückgerollt."

    def add_arguments(self, parser):
        parser.add_argument("--user-id", type=int, required=True)
        parser.add_argument("--company-id", type=int, required=True)
        parser.add_argument("--apply", action="store_true")
        parser.add_argument(
            "--auto-confirm", action="store_true", help="Eindeutige Treffer automatisch bestätigen"
        )

    def handle(self, *args, **options):
        actor = Actor(options["user_id"])
        company_id = options["company_id"]
        actor.require(company_id, "process")
        report = {"dry_run": not options["apply"], "documents": [], "errors": []}
        with transaction.atomic():
            documents = Document.objects.filter(
                company_id=company_id, kind="bank_camt", status="ready", duplicate_of__isnull=True
            ).order_by("created_at", "id")
            for doc in documents.iterator():
                try:
                    result = reconcile_document(
                        actor,
                        str(doc.id),
                        doc.version,
                        f"backfill-v2:{doc.id}:{doc.version}:{options['auto_confirm']}",
                        options["auto_confirm"],
                    )
                    report["documents"].append({"document_id": str(doc.id), **result})
                except DomainError as exc:
                    report["errors"].append({"document_id": str(doc.id), "error": str(exc)})
            if not options["apply"]:
                transaction.set_rollback(True)
        self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
