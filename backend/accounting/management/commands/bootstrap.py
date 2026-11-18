import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from accounting.demo import seed_companies, seed_month
from accounting.jobs import install_schedule


class Command(BaseCommand):
    help = "Initialen Benutzer, technische Wartung und optionale synthetische Beispieldaten anlegen."

    def add_arguments(self, parser):
        parser.add_argument("--demo", action="store_true")
        parser.add_argument("--sample-month")
        parser.add_argument("--classified", action="store_true")
        parser.add_argument("--output")

    def handle(self, *args, **options):
        username = os.getenv("ADMIN_USERNAME", "admin")
        user = get_user_model().objects.filter(username=username).first()
        if not user:
            password = os.getenv("ADMIN_PASSWORD")
            if not password:
                raise CommandError(
                    "ADMIN_PASSWORD für den ersten Start setzen. Kein unsicheres Standardpasswort."
                )
            if len(password) < 12:
                raise CommandError("ADMIN_PASSWORD muss mindestens 12 Zeichen lang sein.")
            user = get_user_model().objects.create_superuser(username, password=password)
        install_schedule()
        if options["demo"] or options["sample_month"]:
            companies = seed_companies(user)
            if options["sample_month"]:
                ids = seed_month(
                    user, companies[0], options["sample_month"], options["classified"], options["output"]
                )
                self.stdout.write(f"Synthetischer Monat angelegt: {len(ids)} Dokumente.")
        self.stdout.write("Bootstrap abgeschlossen; bestehende Passwörter bleiben unverändert.")
