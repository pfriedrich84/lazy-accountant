from datetime import date as Date
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from iso4217 import Currency
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DocumentKind = Literal[
    "incoming_invoice",
    "incoming_credit",
    "receipt",
    "outgoing_invoice",
    "outgoing_cancellation",
    "bank_pdf",
    "bank_camt",
    "security_pdf",
]
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

    @field_validator("rate")
    @classmethod
    def plausible_rate(cls, value):
        if value is not None and not Decimal("0") <= value <= Decimal("100"):
            raise ValueError("Steuersatz muss zwischen 0 und 100 liegen; Vorzeichen bleiben an den Beträgen.")
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
    period_assignment_confirmed: bool = False
    period_assignment_reason: str | None = Field(default=None, max_length=1000)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    net: Decimal | None = None
    tax: Decimal | None = None
    gross: Decimal | None = None
    taxes: list[TaxLine] = Field(default_factory=list, max_length=100)
    subtype: str | None = Field(default=None, max_length=100)
    confirmed_partner_name: str | None = Field(default=None, max_length=300)
    bank_short_name: str | None = Field(default=None, max_length=100)
    valuation_date: Date | None = None
    isin: str | None = Field(default=None, pattern=r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
    note: str = Field(default="", max_length=10000)
    open_points: list[str] = Field(default_factory=list, max_length=100)
    evidence: dict[str, Evidence] = Field(default_factory=dict)

    @field_validator("currency")
    @classmethod
    def iso_currency(cls, value):
        if value is not None:
            Currency(value)  # Reject invented/unknown codes, preserve recognized original currencies.
        return value

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
        for field, title in [
            ("issuer", "Aussteller"),
            ("recipient", "Empfänger"),
            ("number", "Belegnummer"),
            ("date", "Belegdatum"),
            ("currency", "Währung"),
            ("net", "Netto"),
            ("tax", "Steuer"),
            ("gross", "Brutto"),
        ]:
            if getattr(m, field) is None or getattr(m, field) == "":
                issues.append(f"{title} fehlt")
    if any(value is not None for value in [m.net, m.tax, m.gross]) and not m.currency:
        issues.append("Währung fehlt")
    if m.net is not None and m.tax is not None and m.gross is not None:
        exponent = Currency(m.currency).exponent if m.currency else 2
        if exponent is None:
            issues.append("Währung hat keine definierte Minor Unit; Betragsrundung manuell klären")
            exponent = 2
        quantum = Decimal(1).scaleb(-exponent)

        def rounded(value):
            return value.quantize(quantum, rounding=ROUND_HALF_UP)

        if rounded(m.net + m.tax) != rounded(m.gross):
            issues.append("Netto + Steuer stimmt nicht mit Brutto überein")
        if m.taxes:
            if any(t.net is None or t.tax is None or t.rate is None for t in m.taxes):
                issues.append("Steueraufteilung unvollständig")
            else:
                if rounded(sum(t.net for t in m.taxes)) != rounded(m.net) or rounded(
                    sum(t.tax for t in m.taxes)
                ) != rounded(m.tax):
                    issues.append("Steueraufteilung stimmt nicht mit Gesamtsummen überein")
                for t in m.taxes:
                    if rounded(t.net * t.rate / Decimal("100")) != rounded(t.tax):
                        issues.append("Steuerbetrag passt nicht zum Steuersatz")
    if kind in {"bank_pdf", "bank_camt", "security_pdf"}:
        if not account_id:
            issues.append("Konto/Depot ungeklärt")
        if not m.period_start or not m.period_end:
            issues.append("Auszugszeitraum unvollständig")
        elif (m.period_start.year, m.period_start.month) != (m.period_end.year, m.period_end.month):
            if not m.period_assignment_confirmed or not (m.period_assignment_reason or "").strip():
                issues.append(
                    "Mehrmonatiger Auszugszeitraum: Zuordnung ausdrücklich bestätigen und begründen"
                )
    if parser_error:
        issues.append(parser_error)
    issues.extend(m.open_points)
    issues.extend(
        f"Unsicheres Feld {name}: {item.reason}" for name, item in m.evidence.items() if item.uncertain
    )
    return list(dict.fromkeys(issues))
