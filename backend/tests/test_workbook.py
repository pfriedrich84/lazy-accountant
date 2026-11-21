"""Synthetic package acceptance tests for the single accountant workbook."""

import io
import zipfile

import pytest
from openpyxl import load_workbook

from accounting import packages
from accounting.demo import seed_month

pytestmark = pytest.mark.django_db

SHEETS = [
    "Übersicht",
    "Eingangsrechnungen",
    "Ausgangsrechnungen",
    "Zahlungszuordnungen",
    "Bankbewegungen",
    "Wertpapiere",
    "Klärfälle",
    "Inhaltsliste",
]


def open_workbook(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = [n for n in archive.namelist() if n.endswith(".xlsx")]
        assert len(names) == 1, names
        assert not any(n.endswith((".csv", ".json", ".txt")) for n in archive.namelist())
        return load_workbook(io.BytesIO(archive.read(names[0]))), names[0]


def test_single_workbook_preserves_originals_and_has_readable_sheets(user, actor, companies):
    company = companies[0]
    seed_month(user, company, classified=True)
    result = packages.create_package(actor, company.id, ["2026-10"], "single-workbook")
    package = packages.get_package(actor, result["id"])
    data = packages.package_bytes(package)
    workbook, name = open_workbook(data)
    assert name == f"{company.folder}/Monatsuebersicht_2026-10.xlsx"
    assert workbook.sheetnames == SHEETS
    for sheet in workbook:
        assert sheet.freeze_panes in {"A6", "D6"}
        assert sheet.auto_filter.ref
        assert not any(cell.data_type == "f" for row in sheet for cell in row)
    inventory = list(workbook["Inhaltsliste"].iter_rows(min_row=5, values_only=True))
    assert len(inventory) == 9  # eight originals, no self-checksum for the workbook
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for item in package.items.all():
            assert archive.read(item.archive_path)
    assert "Keine Zuordnung bedeutet nicht nachgewiesenes Nichtbezahltsein" in str(
        list(workbook["Übersicht"].values)
    )
