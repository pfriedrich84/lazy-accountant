import socket

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django_q.conf import Conf
from django_q.status import Stat


class Command(BaseCommand):
    help = "Django-Q2-Clusterstatus/Heartbeat dieses Containers prüfen."

    def handle(self, *args, **options):
        active = [
            s
            for s in Stat.get_all()
            if s.host == socket.gethostname()
            and s.status in {Conf.IDLE, Conf.WORKING}
            and (timezone.now() - s.timestamp).total_seconds() < 30
        ]
        if not active:
            raise CommandError("Kein gesunder Django-Q2-Worker mit aktuellem Heartbeat.")
        self.stdout.write("Worker gesund.")
