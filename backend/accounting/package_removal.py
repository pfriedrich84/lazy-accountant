"""Logical removal with durable audit and independently retryable ZIP cleanup."""

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from . import packages, storage
from .auth import DomainError
from .models import Job, Package, PackageRemoval


def removal_data(removal):
    return {
        "package_id": str(removal.package_id),
        "expected_version": removal.expected_version,
        "reason": removal.reason,
        "removed_at": removal.created_at.isoformat(),
        "removed_by": removal.actor_id,
        "status": "completed" if removal.zip_removed_at else "cleanup_pending",
        "zip_removed_at": removal.zip_removed_at.isoformat() if removal.zip_removed_at else None,
        "cleanup_error": removal.cleanup_error,
    }


def preview(actor, company_id, package_id):
    company_id = actor.require(company_id).id
    package = packages.get_package(actor, package_id)
    if package.company_id != company_id:
        raise DomainError("Paket nicht gefunden.", 404)
    children = list(Package.objects.filter(parent=package).values_list("id", flat=True))
    # Conservatively protect the company while any package build is queued/running,
    # including supplements whose ancestor is the package being removed.
    jobs = list(
        Job.objects.filter(company_id=company_id, kind="package").values("id", "status", "payload", "result")
    )
    dispatches = list(package.dispatches.values("id", "status"))
    blockers = []
    if children:
        blockers.append("Referenzierte Nachträge vorhanden; keine Kaskadenlöschung.")
    if dispatches:
        blockers.append("SMTP-/Versandauftrag vorhanden; Versandhistorie bleibt geschützt.")
    if any(job["status"] in {"queued", "running"} for job in jobs):
        blockers.append("Aktiver Paketauftrag der Firma; Abschluss abwarten.")
    # Failed/interrupted builds referencing the parent could later be resumed.
    if any(
        str(job["payload"].get("parent_id") or "") == str(package.id) and job["status"] != "done"
        for job in jobs
    ):
        blockers.append("Fortsetzbarer Nachtragsauftrag referenziert das Paket.")
    removal = PackageRemoval.objects.filter(package=package).first()
    if removal:
        blockers.append("Paket bereits entfernt.")
    return {
        "package": packages.package_data(package, True),
        "children": [str(identifier) for identifier in children],
        "jobs": [
            {"id": str(job["id"]), "status": job["status"]}
            for job in jobs
            if job["status"] in {"queued", "running"}
            or str(job["payload"].get("parent_id") or "") == str(package.id)
            or job["result"].get("id") == str(package.id)
        ],
        "dispatches": [{"id": str(d["id"]), "status": d["status"]} for d in dispatches],
        "download": {
            "available": not removal and not packages.package_blockers(package),
            "semantics": "Bereits autorisierte Downloads können zu Ende laufen; neue Abrufe sind nach Entfernung gesperrt.",
        },
        "blockers": blockers,
        "can_remove": not blockers,
        "required_permission": "process",
        "removal": removal_data(removal) if removal else None,
    }


def remove(actor, company_id, package_id, expected_version, reason, idempotency_key):
    company_id = actor.require(company_id, "process").id
    if (
        type(expected_version) is not int
        or expected_version < 1
        or not isinstance(reason, str)
        or not reason.strip()
        or len(reason) > 2000
        or not isinstance(idempotency_key, str)
        or not 1 <= len(idempotency_key) <= 120
    ):
        raise DomainError("Version, Begründung (max. 2000) und Idempotenzschlüssel (max. 120) erforderlich.")
    reason = reason.strip()
    with transaction.atomic():
        # Same order as package creation/document writers and dispatch queueing.
        get_user_model().objects.select_for_update().get(id=actor.user_id)
        actor.companies("process").select_for_update().get(id=company_id)
        package = Package.objects.select_for_update().filter(id=package_id, company_id=company_id).first()
        if not package:
            raise DomainError("Paket nicht gefunden.", 404)
        prior = PackageRemoval.objects.filter(company_id=company_id, idempotency_key=idempotency_key).first()
        if prior:
            if (
                prior.package_id != package.id
                or prior.expected_version != expected_version
                or prior.reason != reason
            ):
                raise DomainError("Idempotenzschlüssel gehört zu einem anderen Löschauftrag.", 409)
        else:
            if package.version != expected_version:
                raise DomainError("Veraltete Paketversion; Löschvorschau erneut prüfen.", 409)
            check = preview(actor, company_id, package_id)
            if check["blockers"]:
                raise DomainError("Paket kann nicht entfernt werden.", 409, check["blockers"])
            prior = PackageRemoval.objects.create(
                package=package,
                company_id=company_id,
                actor_id=actor.user_id,
                expected_version=expected_version,
                reason=reason,
                idempotency_key=idempotency_key,
            )
    # Only touch the ZIP after the tombstone has committed. Failure is observable
    # and maintenance/replay retries; audit, snapshots and source data are retained.
    cleanup(prior.pk)
    prior.refresh_from_db()
    return removal_data(prior)


def cleanup(removal_id):
    with transaction.atomic():
        removal = (
            PackageRemoval.objects.select_for_update(of=("self",))
            .select_related("package")
            .get(pk=removal_id)
        )
        if removal.zip_removed_at:
            return
        try:
            storage.path(removal.package.path).unlink(missing_ok=True)
        except OSError as exc:
            removal.cleanup_error = type(exc).__name__ + ": ZIP-Bereinigung ausstehend."
        else:
            removal.zip_removed_at = timezone.now()
            removal.cleanup_error = ""
        removal.save(update_fields=["zip_removed_at", "cleanup_error"])
