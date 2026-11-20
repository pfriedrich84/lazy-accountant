"""Versioned inputs shared by REST and MCP; never accept a paid-status override."""

from decimal import Decimal
from uuid import UUID
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator


class BankRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=1, max_length=120)


class BankIdentityRequest(BankRequest):
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason", "idempotency_key")
    @classmethod
    def safe_text(cls, value):
        if not value.strip() or "\x00" in value:
            raise ValueError("Begründung/Schlüssel darf nicht leer sein oder Nullbytes enthalten.")
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ValueError("Ungültiges Unicode.") from exc
        return value


class BankIdentityMergeRequest(BankIdentityRequest):
    duplicate_id: UUID
    canonical_id: UUID
    duplicate_version: int = Field(ge=1, strict=True)
    canonical_version: int = Field(ge=1, strict=True)
    document_versions: dict[UUID, StrictInt] = Field(min_length=1, max_length=100)


class BankIdentityDisputeRequest(BankIdentityRequest):
    duplicate_id: UUID
    duplicate_version: int = Field(ge=1, strict=True)
    canonical_version: int = Field(ge=1, strict=True)


class BankPolicyRequest(BankRequest):
    company_id: int = Field(ge=1, strict=True)
    expected_version: int = Field(ge=0, strict=True)
    enabled: bool = Field(strict=True)
    reason: str = Field(min_length=1, max_length=1000)


class BankCoverageRequest(BankRequest):
    company_id: int = Field(ge=1, strict=True)
    account_id: int = Field(ge=1, strict=True)
    period: str = Field(pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$")
    expected_version: int = Field(ge=0, strict=True)
    state: Literal["confirmed", "disputed", "unknown"]
    document_ids: list[UUID] = Field(default_factory=list, max_length=100)
    document_versions: dict[UUID, StrictInt] = Field(default_factory=dict, max_length=100)
    reason: str = Field(min_length=1, max_length=1000)


class ReconcileRequest(BankRequest):
    document_id: UUID
    base_version: int = Field(ge=1, strict=True)
    auto_confirm: bool = Field(
        default=True,
        description="Neue eindeutige Rechnungszuordnungen bestätigen. Eindeutig gebuchte Bankrückbuchungen berichtigen vorhandene Deckung unabhängig davon.",
    )


class AllocationRequest(BankRequest):
    transaction_id: UUID
    document_id: UUID
    amount: Decimal = Field(gt=0, lt=Decimal("1e14"), max_digits=20, decimal_places=6)
    bank_version: int = Field(ge=1, strict=True)
    document_version: int = Field(ge=1, strict=True)
    reason: str = Field(min_length=1, max_length=1000)


class FXLeg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: UUID
    document_version: int = Field(ge=1, strict=True)
    amount: Decimal = Field(gt=0, lt=Decimal("1e14"), max_digits=20, decimal_places=6)
    bank_principal: Decimal = Field(gt=0, lt=Decimal("1e14"), max_digits=20, decimal_places=6)
    fee: Decimal = Field(ge=0, lt=Decimal("1e14"), max_digits=20, decimal_places=6)


class FXPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    transaction_id: UUID
    bank_version: int = Field(ge=1, strict=True)
    evidence_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    legs: list[FXLeg] = Field(min_length=1, max_length=100)


class FXConfirmRequest(FXPreviewRequest):
    preview_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    reason: str = Field(min_length=1, max_length=1000)
    idempotency_key: str = Field(min_length=1, max_length=120)


class ReverseAllocationRequest(BankRequest):
    allocation_id: UUID
    bank_version: int = Field(ge=1, strict=True)
    reason: str = Field(min_length=1, max_length=1000)


class RevokePartyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_id: int = Field(ge=1)
    party_id: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)


class VerifyPartyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_id: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=300)
    iban: str = Field(min_length=15, max_length=100)
    reason: str = Field(min_length=1, max_length=1000)
