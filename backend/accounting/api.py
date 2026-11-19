import json
import mimetypes

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.http import FileResponse, HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods
from rest_framework.response import Response
from rest_framework.views import APIView, exception_handler as drf_exception_handler

from . import jobs, mail, packages, services, storage, transfers
from .auth import DomainError, issue_token, request_actor
from .models import AccessToken, Account, Category, Dispatch, ImportSource, Job, Package
from .schemas import DocumentResult


def exception_handler(exc, context):
    if isinstance(exc, DomainError):
        return Response({"error": str(exc), "details": exc.details}, status=exc.status)
    from django.core.exceptions import ValidationError
    from django.db import IntegrityError

    if isinstance(exc, (ValueError, TypeError, KeyError, ValidationError, IntegrityError)):
        return Response({"error": "Ungültige oder widersprüchliche Eingabe."}, status=400)
    return drf_exception_handler(exc, context)


@require_http_methods(["GET"])
def csrf(request):
    return JsonResponse({"csrfToken": get_token(request)})


@csrf_protect
@require_http_methods(["POST"])
def sign_in(request):
    try:
        payload = json.loads(request.body)
    except ValueError, UnicodeDecodeError:
        return JsonResponse({"error": "Ungültige Anmeldung."}, status=400)
    # Django's cache-backed throttle is also used before a session exists.
    from django.core.cache import cache

    key = "login:" + request.META.get("REMOTE_ADDR", "unknown")
    attempts = cache.get(key, 0)
    if attempts >= 20:
        return JsonResponse({"error": "Zu viele Versuche. Bitte später erneut versuchen."}, status=429)
    user = authenticate(request, username=payload.get("username", ""), password=payload.get("password", ""))
    if user is None:
        cache.set(key, attempts + 1, 300)
        return JsonResponse({"error": "Anmeldung fehlgeschlagen."}, status=401)
    cache.delete(key)
    login(request, user)
    return JsonResponse({"id": user.id, "username": user.username, "csrfToken": get_token(request)})


@csrf_protect
@require_http_methods(["POST"])
def sign_out(request):
    logout(request)
    return JsonResponse({"ok": True})


class Session(APIView):
    def get(self, request):
        return Response({"id": request.user.id, "username": request.user.username})


class Companies(APIView):
    def get(self, request):
        return Response([services.company_data(c) for c in request_actor(request).companies()])

    def post(self, request):
        return Response(services.create_company(request_actor(request), request.data), status=201)


class CompanyDetail(APIView):
    def get(self, request, company_id):
        return Response(services.known_assignments(request_actor(request), company_id))

    def patch(self, request, company_id):
        return Response(services.update_company(request_actor(request), company_id, request.data))


class Assignments(APIView):
    def post(self, request, company_id, collection):
        if collection not in {"accounts", "categories"}:
            raise DomainError("Zuordnung nicht gefunden.", 404)
        actor = request_actor(request)
        company = actor.require(company_id, "admin")
        model = Account if collection == "accounts" else Category
        allowed = {"name", "kind", "identifier"} if model is Account else {"name"}
        values = {k: v for k, v in request.data.items() if k in allowed}
        obj = model(company=company, **values)
        obj.full_clean()
        obj.save()
        return Response({"id": obj.id, **values}, status=201)

    def patch(self, request, company_id, collection, object_id=None):
        if collection not in {"accounts", "categories"}:
            raise DomainError("Zuordnung nicht gefunden.", 404)
        actor = request_actor(request)
        company = actor.require(company_id, "admin")
        model = Account if collection == "accounts" else Category
        obj = model.objects.filter(id=object_id, company=company).first()
        if not obj:
            raise DomainError("Zuordnung nicht gefunden.", 404)
        allowed = {"name", "identifier"} if model is Account else {"name"}
        for k in allowed:
            if k in request.data:
                setattr(obj, k, request.data[k])
        obj.full_clean()
        obj.save()
        return Response({"id": obj.id, "name": obj.name})


class Documents(APIView):
    def get(self, request):
        p = request.query_params
        return Response(
            services.list_documents(
                request_actor(request),
                **{
                    k: p[k]
                    for k in (
                        "company_id",
                        "period",
                        "status",
                        "kind",
                        "search",
                        "category_id",
                        "cursor",
                        "limit",
                    )
                    if k in p
                },
            )
        )

    def post(self, request):
        files = request.FILES.getlist("files") or request.FILES.getlist("file")
        if not files or len(files) > 30:
            raise DomainError("Ein bis 30 Dateien auswählen.")
        results = []
        for index, f in enumerate(files):
            if f.size > settings.MAX_FILE_BYTES:
                raise DomainError("Datei zu groß.", 413)
            key = request.headers.get("Idempotency-Key")
            results.append(
                services.ingest(
                    request_actor(request),
                    f.name,
                    f.read(),
                    request.data.get("company_id") or None,
                    f"{key}:{index}" if key else None,
                )
            )
        return Response({"results": results}, status=201)


class DocumentDetail(APIView):
    def get(self, request, document_id):
        return Response(
            services.document_data(services.get_document(request_actor(request), document_id), True)
        )

    def put(self, request, document_id):
        payload = dict(request.data)
        payload["document_id"] = str(document_id)
        return Response(services.save_result(request_actor(request), payload))


class DocumentFile(APIView):
    def get(self, request, document_id, representation):
        actor = request_actor(request)
        doc = services.get_document(actor, document_id)
        if representation == "duplicates":
            return Response(services.duplicate_hints(actor, document_id))
        if representation == "text":
            return Response(
                services.readable_document(actor, document_id, int(request.query_params.get("page", 1)))
            )
        if representation == "page":
            data = services.readable_document(
                actor, document_id, int(request.query_params.get("page", 1)), image=True
            )
            return HttpResponse(data, content_type="image/png")
        data = storage.read_original(doc)
        response = HttpResponse(data, content_type=doc.media_type)
        from django.utils.http import content_disposition_header

        response["Content-Disposition"] = content_disposition_header(
            doc.media_type == "application/xml", storage.safe_filename(doc.original_name)
        )
        response["Cache-Control"] = "private, no-store"
        response["Content-Security-Policy"] = "sandbox"
        return response


class Packages(APIView):
    def get(self, request):
        actor = request_actor(request)
        qs = Package.objects.filter(company__in=actor.companies()).order_by("-created_at")
        if request.query_params.get("company_id"):
            qs = qs.filter(company_id=request.query_params["company_id"])
        return Response([packages.package_data(p) for p in qs[:200]])

    def post(self, request):
        p = request.data
        return Response(
            jobs.enqueue_job(
                request_actor(request),
                p["company_id"],
                "package",
                p["idempotency_key"],
                {"periods": p["periods"], "parent_id": p.get("parent_id")},
            ),
            status=202,
        )


class Preview(APIView):
    def post(self, request):
        p = request.data
        return Response(
            packages.package_preview(
                request_actor(request), p["company_id"], p["periods"], p.get("parent_id")
            )
        )


class PackageDetail(APIView):
    def get(self, request, package_id, action=None):
        p = packages.get_package(request_actor(request), package_id)
        if action == "download":
            response = HttpResponse(packages.package_bytes(p), content_type="application/zip")
            response["Content-Disposition"] = f'attachment; filename="paket-v{p.version}.zip"'
            response["Cache-Control"] = "private, no-store"
            return response
        return Response(packages.package_data(p, True))

    def post(self, request, package_id, action=None):
        if action != "send":
            raise DomainError("Aktion nicht gefunden.", 404)
        return Response(
            mail.queue_dispatch(
                request_actor(request),
                package_id,
                request.data["idempotency_key"],
                request.data.get("resend_of"),
            ),
            status=202,
        )


class Dispatches(APIView):
    def get(self, request, dispatch_id=None):
        actor = request_actor(request)
        qs = Dispatch.objects.filter(package__company__in=actor.companies()).order_by("-created_at")
        if dispatch_id:
            d = qs.filter(id=dispatch_id).first()
            if not d:
                raise DomainError("Versandauftrag nicht gefunden.", 404)
            return Response(mail.dispatch_data(d))
        if request.query_params.get("company_id"):
            qs = qs.filter(package__company_id=request.query_params["company_id"])
        return Response([mail.dispatch_data(d) for d in qs[:200]])


class Jobs(APIView):
    def get(self, request, job_id=None):
        actor = request_actor(request)
        qs = Job.objects.filter(company__in=actor.companies()).order_by("-created_at")
        if job_id:
            j = qs.filter(id=job_id).first()
            if not j:
                raise DomainError("Auftrag nicht gefunden.", 404)
            return Response(jobs.job_data(j))
        if request.query_params.get("company_id"):
            qs = qs.filter(company_id=request.query_params["company_id"])
        return Response([jobs.job_data(j) for j in qs[:100]])

    def post(self, request, job_id=None, action=None):
        if job_id:
            if action == "resume":
                return Response(jobs.resume_job(request_actor(request), job_id))
            return Response(
                jobs.finish_agent_run(
                    request_actor(request),
                    job_id,
                    request.data.get("result", {}),
                    request.data.get("status", "done"),
                )
            )
        p = request.data
        if p["kind"] not in {"imap", "agent"}:
            raise DomainError("Ungültige Auftragsart.")
        return Response(
            jobs.enqueue_job(
                request_actor(request), p["company_id"], p["kind"], p["idempotency_key"], p.get("payload", {})
            ),
            status=202,
        )


class MailSettings(APIView):
    def get(self, request, company_id):
        return Response(mail.mail_config(request_actor(request), company_id))

    def put(self, request, company_id):
        return Response(mail.mail_config(request_actor(request), company_id, request.data))


class ImportErrors(APIView):
    def get(self, request, company_id):
        actor = request_actor(request)
        actor.require(company_id)
        return Response(
            list(
                ImportSource.objects.filter(mailbox__company_id=company_id)
                .exclude(error="")
                .order_by("-id")
                .values("id", "provenance", "error")[:200]
            )
        )


class Tokens(APIView):
    def get(self, request):
        actor = request_actor(request)
        if actor.token_id:
            raise DomainError("Tokenverwaltung nur in einer Benutzersitzung.", 403)
        return Response(
            list(
                AccessToken.objects.filter(user=request.user).values(
                    "id", "name", "prefix", "scopes", "revoked", "created_at", "expires_at"
                )
            )
        )

    def post(self, request):
        p = request.data
        return Response(
            issue_token(request_actor(request), p["name"], p["company_ids"], p["scopes"]), status=201
        )

    def delete(self, request, token_id):
        actor = request_actor(request)
        if actor.token_id:
            raise DomainError("Tokenverwaltung nur in einer Benutzersitzung.", 403)
        AccessToken.objects.filter(user=request.user, id=token_id).update(revoked=True)
        return Response({"ok": True})


class UploadTransfer(APIView):
    # Raw binary body is deliberately not parsed as JSON or multipart.
    parser_classes = []

    def put(self, request, upload_id):
        if int(request.headers.get("Content-Length", 0)) > settings.MAX_FILE_BYTES:
            raise DomainError("Datei zu groß.", 413)
        data = request._request.body
        return Response(transfers.put_upload(request_actor(request), upload_id, data))


class Schema(APIView):
    def get(self, request):
        return Response(DocumentResult.model_json_schema())


class Folders(APIView):
    def get(self, request, company_id):
        return Response(
            services.month_folders(
                request_actor(request),
                company_id,
                request.query_params.get("period", ""),
                request.query_params.get("cursor"),
            )
        )


def health(request):
    from django.db import connection

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return JsonResponse({"status": "ok"})
    except Exception:
        return JsonResponse({"status": "unhealthy"}, status=503)


def spa(request, resource=""):
    root = settings.SPA_ROOT.resolve()
    target = (root / resource).resolve()
    if not target.is_relative_to(root):
        return HttpResponse(status=404)
    if not resource or not target.is_file():
        if resource.startswith(("api/", "mcp/", "assets/")):
            return HttpResponse(status=404)
        target = root / "index.html"
    if not target.is_file():
        return HttpResponse("Frontend noch nicht gebaut. Siehe README.", status=503)
    response = FileResponse(
        target.open("rb"), content_type=mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    )
    if target.name == "index.html":
        response["Cache-Control"] = "no-cache"
    return response
