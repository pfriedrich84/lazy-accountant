from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from accounting.jobs import maintenance
from accounting.models import Job


class Command(BaseCommand):
    help = "Nur bei Offline-Restore: verwaiste laufende Aufträge sicher freigeben; SMTP-Ausgänge bleiben unbekannt."

    def handle(self, *args, **options):
        Job.objects.filter(status="running").exclude(kind="agent").update(heartbeat=timezone.now() - timedelta(minutes=10))
        maintenance()
        self.stdout.write("Wiederanlauf vorbereitet. SMTP mit unbekanntem Ausgang wird nicht automatisch erneut versendet.")
