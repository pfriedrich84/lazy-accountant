import uuid

import pytest

from django.utils import timezone

from accounting import services, storage
from accounting.auth import DomainError
from accounting.models import Company, Document

pytestmark = pytest.mark.django_db


def make_document(actor, company, index, **changes):
    return Document(
        id=uuid.UUID(int=index),
        company=company,
        inbox_owner_id=actor.user_id,
        original_name=f"original-{index}.pdf",
        original_path=f"_originals/{index}.pdf",
        sha256=f"{index:064x}",
        size=10,
        media_type="application/pdf",
        security_status="clean",
        kind="security_pdf",
        period="2026-10",
        status="ready" if index <= 101 else "review",
        **changes,
    )


def seed_month(actor, companies):
    company, other = companies
    rows = [make_document(actor, company, index) for index in range(1, 106)]
    rows[-1].kind = ""
    rows[-2].status = "new"
    excluded = make_document(
        actor,
        company,
        106,
        is_excluded=True,
        exclusion_reason="Test: kein Beleg",
        excluded_at=timezone.now(),
        excluded_by_id=actor.user_id,
    )
    outside_month = make_document(actor, company, 107)
    outside_month.period = "2026-11"
    Document.objects.bulk_create([*rows, excluded, outside_month, make_document(actor, other, 108)])
    return company


def test_month_counts_cover_all_pages_and_exclude_other_scopes(actor, companies):
    company = seed_month(actor, companies)
    first = services.month_folders(actor, company.id, "2026-10")
    assert first["summary"] == {"total": 105, "ready": 101, "open": 4}
    assert first["total"] == 105
    folder = next(f for f in first["folders"] if f["name"] == "Wertpapiere")
    assert (folder["total"], folder["ready"], folder["open"], len(folder["files"])) == (104, 101, 3, 100)
    assert first["unfiled"]["total"] == 1
    assert first["unfiled"]["files"] == []
    assert {f["name"] for f in first["folders"]} == set(storage.FOLDERS)

    second = services.month_folders(actor, company.id, "2026-10", cursor=first["next_cursor"])
    assert second["summary"] == first["summary"]
    assert second["next_cursor"] is None
    files = [d for page in (first, second) for f in page["folders"] for d in f["files"]]
    files += second["unfiled"]["files"]
    assert len(files) == len({d["id"] for d in files}) == 105


def test_open_filter_runs_before_pagination_but_preserves_month_summary(actor, companies, client):
    company = seed_month(actor, companies)
    response = client.get(f"/api/folders/{company.id}/", {"period": "2026-10", "status": "open"})
    assert response.status_code == 200
    data = response.json()
    assert data["summary"] == {"total": 105, "ready": 101, "open": 4}
    assert data["total"] == 4
    assert data["next_cursor"] is None
    files = [d for f in data["folders"] for d in f["files"]] + data["unfiled"]["files"]
    assert len(files) == 4
    assert all(d["status"] in {"new", "review"} for d in files)


def test_open_documents_can_be_paginated_without_losing_month_counts(actor, companies):
    company = companies[0]
    rows = [make_document(actor, company, index) for index in range(1, 106)]
    for row in rows:
        row.status = "new"
    Document.objects.bulk_create(rows)
    first = services.month_folders(actor, company.id, "2026-10", status="open")
    second = services.month_folders(actor, company.id, "2026-10", cursor=first["next_cursor"], status="open")
    assert first["summary"] == second["summary"] == {"total": 105, "ready": 0, "open": 105}
    assert sum(len(f["files"]) for f in first["folders"]) == 100
    assert sum(len(f["files"]) for f in second["folders"]) == 5
    assert second["next_cursor"] is None


def test_empty_month_returns_zero_counts_and_real_folders(actor, companies):
    result = services.month_folders(actor, companies[0].id, "2026-10")
    assert result["summary"] == {"total": 0, "ready": 0, "open": 0}
    assert result["next_cursor"] is None
    assert all(f["total"] == 0 and f["files"] == [] for f in result["folders"])


def test_summary_requires_company_access_and_valid_filter(actor, companies):
    other = Company.objects.create(name="Private", folder="Private")
    with pytest.raises(DomainError):
        services.month_folders(actor, other.id, "2026-10")
    with pytest.raises(DomainError, match="Statusfilter"):
        services.month_folders(actor, companies[0].id, "2026-10", status="invalid")
