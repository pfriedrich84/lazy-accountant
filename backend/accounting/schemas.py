from datetime import date as Date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DocumentKind = Literal["incoming_invoice", "incoming_credit", "receipt", "outgoing_invoice", "outgoing_cancellation", "bank_pdf", "bank_camt", "security_pdf"]
Period = str


class TaxLine(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rate: Decimal | None = None
    net: Decimal | None = None
    tax: Decimal | None = None

    @field_validator("rate", "net", "tax", mode="before")
    @classmethod
    def decimal_input(cls, value):
        if isinstance(value, float):
            raise ValueError("Dezimalbeträge als Zeichenfolge übergeben, nicht als Float.")
        return value

    @field_validator("rate", "net", "tax")
    @classmethod
    def finite(cls, value):
        if value is not None and (not value.is_finite() or abs(value) >= Decimal("1e16")):
            raise ValueError("Ungültiger Dezimalbetrag.")
        return value


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: int | None = Field(default=None, ge=1)
    excerpt: str = Field(default="", max_length=2000)
    uncertain: bool = False
    reason: str = Field(default="", max_length=1000)


class Metadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    issuer: str | None = Field(default=None, max_length=300)
    recipient: str | None = Field(default=None, max_length=300)
    number: str | None = Field(default=None, max_length=160)
    date: Date | None = None
    service_date: Date | None = None
    due_date: Date | None = None
    period_start: Date | None = None
    period_end: Date | None = None
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    net: Decimal | None = None
    tax: Decimal | None = None
    gross: Decimal | None = None
    taxes: list[TaxLine] = Field(default_factory=list, max_length=100)
    subtype: str | None = Field(default=None, max_length=100)
    note: str = Field(default="", max_length=10000)
    open_points: list[str] = Field(default_factory=list, max_length=100)
    evidence: dict[str, Evidence] = Field(default_factory=dict)

    @field_validator("net", "tax", "gross", mode="before")
    @classmethod
    def decimal_input(cls, value):
        return TaxLine.decimal_input(value)

    @field_validator("net", "tax", "gross")
    @classmethod
    def finite(cls, value):
        return TaxLine.finite(value)

    @model_validator(mode="after")
    def date_order(self):
        if self.period_start and self.period_end and self.period_end < self.period_start:
            raise ValueError("Auszugsende liegt vor dem Beginn.")
        return self


class DocumentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str
    base_version: int = Field(ge=1)
    company_id: int | None = None
    kind: DocumentKind | None = None
    period: str | None = Field(default=None, pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$")
    account_id: int | None = None
    category_id: int | None = None
    metadata: Metadata = Field(default_factory=Metadata)
    approve: bool = False
    related_ids: list[str] = Field(default_factory=list, max_length=100)
    duplicate_of: str | None = None


def validation_issues(kind, company_id, period, account_id, metadata, parser_error=""):
    issues = []
    if not company_id:
        issues.append("Firma ungeklärt")
    if not kind:
        issues.append("Dokumentart ungeklärt")
    if not period:
        issues.append("Übergabemonat ungeklärt")
    m = Metadata.model_validate(metadata)
    if kind in {"incoming_invoice", "incoming_credit", "outgoing_invoice", "outgoing_cancellation"}:
        for field, title in [("issuer", "Aussteller"), ("recipient", "Empfänger"), ("number", "Belegnummer"), ("date", "Belegdatum"), ("currency", "Währung"), ("net", "Netto"), ("tax", "Steuer"), ("gross", "Brutto")]:
            if getattr(m, field) is None or getattr(m, field) == "":
                issues.append(f"{title} fehlt")
    if m.net is not None and m.tax is not None and m.gross is not None:
        quantum = Decimal("1") if m.currency in {"JPY", "KRW", "CLP"} else Decimal("0.001") if m.currency in {"KWD", "BHD", "OMR", "TND"} else Decimal("0.01")
        if (m.net + m.tax).quantize(quantum) != m.gross.quantize(quantum):
            issues.append("Netto + Steuer stimmt nicht mit Brutto überein")
        if m.taxes:
            if any(t.net is None or t.tax is None or t.rate is None for t in m.taxes):
                issues.append("Steueraufteilung unvollständig")
            else:
                if sum(t.net for t in m.taxes).quantize(quantum) != m.net.quantize(quantum) or sum(t.tax for t in m.taxes).quantize(quantum) != m.tax.quantize(quantum):
                    issues.append("Steueraufteilung stimmt nicht mit Gesamtsummen überein")
                for t in m.taxes:
                    if (t.net * t.rate / Decimal("100")).quantize(quantum) != t.tax.quantize(quantum):
                        issues.append("Steuerbetrag passt nicht zum Steuersatz")
    if kind in {"bank_pdf", "bank_camt", "security_pdf"}:
        if not account_id:
            issues.append("Konto/Depot ungeklärt")
        if not m.period_start or not m.period_end:
            issues.append("Auszugszeitraum unvollständig")
        elif (m.period_start.year, m.period_start.month) != (m.period_end.year, m.period_end.month):
            issues.append("Mehrmonatiger Auszugszeitraum: Zuordnung prüfen")
    if parser_error:
        issues.append(parser_error)
    issues.extend(m.open_points)
    issues.extend(f"Unsicheres Feld {name}: {item.reason}" for name, item in m.evidence.items() if item.uncertain)
    return list(dict.fromkeys(issues))
