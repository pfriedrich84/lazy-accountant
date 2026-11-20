import io
import zipfile

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounting import storage
from accounting.models import Dispatch, Document, FileOperation, ImportSource, Package


class Command(BaseCommand):
    help = "Originale, physische Zuordnungen, Paket-Snapshots, Mailteile und erhaltene Fehleranhänge prüfen."

    def add_arguments(self, parser):
        parser.add_argument(
            "--repair",
            action="store_true",
            help="Nur ausstehende journalisierte Ablageoperationen erneut ausführen.",
        )

    def handle(self, *args, **options):
        if options["repair"]:
            storage.reconcile()
        errors = []
        for doc in Document.objects.select_related("company").iterator():
            try:
                if doc.security_status != "clean":
                    quarantine = storage.path(doc.quarantine_path or doc.original_path).read_bytes()
                    if storage.checksum(quarantine) != doc.sha256:
                        raise ValueError("Quarantäne-Prüfsumme falsch")
                    continue
                original = storage.read_original(doc)
                if doc.filed_path != storage.desired_path(doc):
                    raise ValueError("Physische Zuordnung noch nicht aktuell")
                if storage.path(doc.filed_path).read_bytes() != original:
                    raise ValueError("Abweichende Originalbytes in Monats-/Eingangsablage")
                if doc.company_id and doc.period:
                    year, month = doc.period.split("-")
                    if not all(
                        storage.path(f"{doc.company.folder}/{year}/{month}/{f}").is_dir()
                        for f in storage.FOLDERS
                    ):
                        raise ValueError("Monatsordner unvollständig")
            except Exception as e:
                errors.append(f"Dokument {doc.id}: {e}")
        for package in Package.objects.iterator():
            try:
                with transaction.atomic():
                    # Serialize with removal, without blocking a supplement's
                    # parent FK check while its documents are locked.
                    package = Package.objects.select_for_update(no_key=True).get(pk=package.pk)
                    removal = getattr(package, "removal", None)
                    if removal and removal.zip_removed_at:
                        continue
                    try:
                        data = storage.path(package.path).read_bytes()
                    except FileNotFoundError:
                        # Cleanup can unlink the ZIP before its completion marker
                        # is persisted (including a crash in that window).
                        if removal:
                            continue
                        raise
                    if storage.checksum(data) != package.sha256:
                        raise ValueError("ZIP-Prüfsumme falsch")
                    with zipfile.ZipFile(io.BytesIO(data)) as archive:
                        for item in package.items.all():
                            if storage.checksum(archive.read(item.archive_path)) != item.sha256:
                                raise ValueError(
                                    f"Prüfsumme des Snapshot-Dokuments {item.document_id} falsch"
                                )
            except Exception as e:
                errors.append(f"Paket {package.id}: {e}")
        for dispatch in Dispatch.objects.iterator():
            for part in dispatch.parts:
                try:
                    if storage.checksum(storage.path(part["path"]).read_bytes()) != part["sha256"]:
                        raise ValueError("Prüfsumme falsch")
                except Exception as e:
                    errors.append(f"Mailteil {dispatch.id}/{part['number']}: {e}")
        for source in ImportSource.objects.exclude(error="").iterator():
            if source.provenance.get("preserved_path"):
                try:
                    if (
                        storage.checksum(storage.path(source.provenance["preserved_path"]).read_bytes())
                        != source.provenance["sha256"]
                    ):
                        raise ValueError("Prüfsumme falsch")
                except Exception as e:
                    errors.append(f"Fehleranhang {source.id}: {e}")
        if FileOperation.objects.filter(status="pending", document__security_status="clean").exists():
            errors.append("Es gibt ausstehende Dateioperationen.")
        if errors:
            raise CommandError("Integritätsprüfung fehlgeschlagen:\n" + "\n".join(errors))
        self.stdout.write(
            f"Integrität OK: {Document.objects.count()} Dokumente, {Package.objects.count()} Pakete, {Dispatch.objects.count()} Versandaufträge."
        )
