import hashlib
import secrets
from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from .models import AccessToken, Company, Membership


class DomainError(Exception):
    def __init__(self, message, status=400, details=None):
        super().__init__(message)
        self.status = status
        self.details = details


@dataclass(frozen=True)
class Actor:
    user_id: int
    token_id: int | None = None

    def companies(self, permission="read"):
        ids = Membership.objects.filter(user_id=self.user_id, **{f"can_{permission}": True}).values("company_id")
        companies = Company.objects.filter(id__in=ids)
        if self.token_id:
            token = AccessToken.objects.get(id=self.token_id)
            if permission not in token.scopes:
                return Company.objects.none()
            companies = companies.filter(accesstoken=token)
        return companies

    def require(self, company_id, permission="read"):
        try:
            return self.companies(permission).get(id=company_id)
        except (Company.DoesNotExist, ValueError, TypeError):
            raise DomainError("Firma nicht gefunden oder Berechtigung fehlt.", 404) from None

    def require_inbox(self, owner_id, permission="read"):
        if self.user_id != owner_id:
            raise DomainError("Dokument nicht gefunden.", 404)
        if self.token_id:
            token = AccessToken.objects.get(id=self.token_id)
            # Unassigned documents are owner-scoped, and only tokens explicitly permitted for inbox see them.
            if "inbox" not in token.scopes or permission not in token.scopes:
                raise DomainError("Eingangsberechtigung fehlt.", 403)


def token_actor(raw):
    digest = hashlib.sha256(raw.encode()).hexdigest()
    token = AccessToken.objects.select_related("user").filter(digest=digest, revoked=False, user__is_active=True).first()
    if not token or (token.expires_at and token.expires_at <= timezone.now()):
        raise DomainError("Ungültiger oder abgelaufener Zugang.", 401)
    return Actor(token.user_id, token.id)


def issue_token(actor, name, company_ids, scopes):
    if actor.token_id:
        raise DomainError("Token können keine weiteren Token erzeugen.", 403)
    if not scopes or set(scopes) - {"read", "process", "send", "admin", "inbox"}:
        raise DomainError("Ungültige Token-Berechtigungen.")
    for cid in company_ids:
        actor.require(cid, "admin")
        for scope in set(scopes) - {"inbox"}:
            actor.require(cid, scope)
    raw = "la_" + secrets.token_urlsafe(40)
    t = AccessToken.objects.create(user_id=actor.user_id, name=name[:120], digest=hashlib.sha256(raw.encode()).hexdigest(), prefix=raw[:10], scopes=scopes)
    t.companies.set(company_ids)
    return {"id": t.id, "token": raw, "prefix": t.prefix}


class BearerAuthentication(BaseAuthentication):
    def authenticate(self, request):
        header = request.headers.get("Authorization", "")
        if not header:
            return None
        if not header.startswith("Bearer "):
            raise AuthenticationFailed("Bearer-Token erwartet.")
        try:
            actor = token_actor(header[7:])
        except DomainError as e:
            raise AuthenticationFailed(str(e)) from e
        return get_user_model().objects.get(id=actor.user_id), AccessToken.objects.get(id=actor.token_id)

    def authenticate_header(self, request):
        return "Bearer"


def request_actor(request):
    return Actor(request.user.id, request.auth.id if isinstance(request.auth, AccessToken) else None)
