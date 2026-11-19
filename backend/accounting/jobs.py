"""Django-Q2 handles transport; these rows guard business side effects and resumption."""

import hashlib
import json
import logging
from datetime import timedelta

from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.utils import timezone
from django_q.models import Schedule
from django_q.tasks import async_task

from .auth import Actor, DomainError
from .models import Dispatch, Job, Mailbox, Membership, SendAttempt

logger = logging.getLogger(__name__)


def job_data(j):
    return {
        "id": str(j.id),
        "company_id": j.company_id,
        "kind": j.kind,
        "status": j.status,
        "result": j.result,
        "error": j.error,
        "created_at": j.created_at.isoformat(),
        "started_at": j.started_at,
        "finished_at": j.finished_at,
    }


def enqueue_job(actor, company_id, kind, idempotency_key, payload=None):
    actor.require(company_id, "send" if kind == "dispatch" else "process")
    if (
        kind not in {"imap", "package", "dispatch", "agent"}
        or not idempotency_key
        or len(idempotency_key) > 120
    ):
        raise DomainError("Ungültiger Auftrag oder Idempotenzschlüssel.")
    payload = payload or {}
    with transaction.atomic():
        j, created = Job.objects.get_or_create(
            company_id=company_id,
            kind=kind,
            idempotency_key=idempotency_key,
            defaults={"actor_id": actor.user_id, "payload": payload},
        )
        if not created and j.payload != payload:
            raise DomainError("Idempotenzschlüssel gehört zu einem anderen Auftrag.", 409)
        if created and kind != "agent":
            transaction.on_commit(lambda: _publish(j.id))
    return job_data(j)


def _publish(job_id):
    try:
        async_task("accounting.jobs.run_job", str(job_id))
    except Exception:
        # Durable queued Job remains discoverable by maintenance; no untracked side effect.
        logger.exception("Queue publish failed for job %s", job_id)


def run_job(job_id):
    with transaction.atomic():
        job = Job.objects.select_for_update().get(id=job_id)
        if job.status != "queued":
            return job_data(job)
        job.status, job.started_at, job.heartbeat = "running", timezone.now(), timezone.now()
        job.save(update_fields=["status", "started_at", "heartbeat"])
    try:
        if job.kind == "imap":
            from .mail import scan_mailbox

            if (
                job.payload.get("nightly_date")
                and not Mailbox.objects.filter(company_id=job.company_id, enabled=True).exists()
            ):
                result = {"skipped": "Nächtlicher Abruf inzwischen deaktiviert."}
            else:
                result = scan_mailbox(job)
        elif job.kind == "package":
            from .packages import create_package

            result = create_package(
                Actor(job.actor_id),
                job.company_id,
                job.payload["periods"],
                job.idempotency_key,
                job.payload.get("parent_id"),
            )
        elif job.kind == "dispatch":
            from .mail import send_dispatch

            result = send_dispatch(job)
        else:
            raise DomainError("Dieser Auftrag wird durch den externen Agenten abgeschlossen.")
        job.status, job.result, job.error = "done", json.loads(json.dumps(result, cls=DjangoJSONEncoder)), ""
    except Exception as e:
        # Do not log mail credentials or document contents.
        job.status = "failed"
        job.error = (
            str(e)[:2000]
            if isinstance(e, DomainError)
            else f"{type(e).__name__}: Verarbeitung fehlgeschlagen; Originale und Fortschritt erhalten."
        )
        logger.error("Job %s failed (%s)", job.id, type(e).__name__)
    job.finished_at = timezone.now()
    with transaction.atomic():
        job.save(update_fields=["status", "result", "error", "finished_at"])
        # One nightly import may need several bounded scans. Persist the next
        # batch atomically with completion, so a worker restart cannot lose it.
        if (
            job.kind == "imap"
            and job.status == "done"
            and job.payload.get("nightly_date")
            and job.result.get("remaining", 0) > 0
            and job.result.get("messages", 0) > 0
            and Mailbox.objects.filter(company_id=job.company_id, enabled=True).exists()
        ):
            cursor = json.dumps(
                [job.payload["nightly_date"], job.result["uidvalidity"], job.result["last_uid"]]
            )
            key = "nightly-batch:" + hashlib.sha256(cursor.encode()).hexdigest()
            payload = {
                **job.payload,
                "until_uid": job.result["snapshot_uid"],
                "snapshot_uidvalidity": job.result["uidvalidity"],
            }
            enqueue_job(Actor(job.actor_id), job.company_id, "imap", key, payload)
    return job_data(job)


def resume_job(actor, job_id):
    with transaction.atomic():
        job = Job.objects.select_for_update().filter(id=job_id).first()
        if not job:
            raise DomainError("Auftrag nicht gefunden.", 404)
        actor.require(job.company_id, "process")
        if job.kind not in {"imap", "package"} or job.status not in {"failed", "interrupted"}:
            raise DomainError(
                "Nur unterbrochene/fehlgeschlagene Import- und Paketaufträge können fortgesetzt werden."
            )
        job.status, job.error = "queued", ""
        job.save(update_fields=["status", "error"])
        transaction.on_commit(lambda: _publish(job.id))
    return job_data(job)


def finish_agent_run(actor, job_id, result, status="done"):
    with transaction.atomic():
        j = Job.objects.select_for_update().filter(id=job_id).first()
        if not j:
            raise DomainError("Auftrag nicht gefunden.", 404)
        actor.require(j.company_id, "process")
        if j.kind != "agent" or status not in {"done", "failed", "running"}:
            raise DomainError("Ungültiger Agentenstatus.")
        if j.status == "done":
            return job_data(j)
        j.status, j.result, j.finished_at = status, result, timezone.now() if status != "running" else None
        j.save(update_fields=["status", "result", "finished_at"])
    return job_data(j)


def maintenance():
    from .storage import reconcile

    from .security import maintenance as scan_maintenance

    scan_maintenance()
    reconcile()
    cutoff = timezone.now() - timedelta(seconds=480)
    for job_id in Job.objects.filter(status="running", heartbeat__lt=cutoff).values_list("id", flat=True):
        with transaction.atomic():
            job = Job.objects.select_for_update().get(id=job_id)
            if job.status != "running":
                continue
            if job.kind == "dispatch":
                dispatch_id = job.payload.get("dispatch_id")
                SendAttempt.objects.filter(dispatch_id=dispatch_id, status="sending").update(
                    status="unknown",
                    detail="Worker unterbrochen; SMTP-Ausgang unbekannt.",
                    finished_at=timezone.now(),
                )
                Dispatch.objects.filter(id=dispatch_id).update(status="unknown")
                job.status = "interrupted"
                job.error = "Versand unterbrochen. Unbekannten Ausgang prüfen; kein automatischer Neuversand."
            else:
                job.status = "queued"
            job.save(update_fields=["status", "error"])
    for job_id in Job.objects.filter(status="queued").exclude(kind="agent").values_list("id", flat=True):
        _publish(job_id)
    # Technical upkeep remains minutely; IMAP starts only once per local night.
    # A one-hour start window tolerates scheduler delays without daytime catch-up.
    local_now = timezone.localtime(timezone.now(), timezone.get_default_timezone())
    if local_now.hour != 3:
        return
    nightly_date = local_now.date().isoformat()
    for mailbox in Mailbox.objects.filter(enabled=True):
        if Job.objects.filter(
            company_id=mailbox.company_id, kind="imap", status__in=["queued", "running"]
        ).exists():
            continue
        user_id = (
            Membership.objects.filter(company_id=mailbox.company_id, can_process=True, user__is_active=True)
            .values_list("user_id", flat=True)
            .first()
        )
        if user_id:
            enqueue_job(
                Actor(user_id),
                mailbox.company_id,
                "imap",
                "nightly:" + nightly_date,
                {"nightly_date": nightly_date},
            )


def install_schedule():
    Schedule.objects.update_or_create(
        name="technical-maintenance",
        defaults={
            "func": "accounting.jobs.maintenance",
            "schedule_type": Schedule.MINUTES,
            "minutes": 1,
            "repeats": -1,
        },
    )
