"""Versioned inputs shared by REST and MCP; never accept a paid-status override."""

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class BankRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=1, max_length=120)


class ReconcileRequest(BankRequest):
    document_id: UUID
    base_version: int = Field(ge=1, strict=True)
    auto_confirm: bool = True


class AllocationRequest(BankRequest):
    transaction_id: UUID
    document_id: UUID
    amount: Decimal = Field(gt=0, lt=Decimal("1e14"), max_digits=20, decimal_places=6)
    bank_version: int = Field(ge=1, strict=True)
    document_version: int = Field(ge=1, strict=True)
    reason: str = Field(min_length=1, max_length=1000)


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
