from django.contrib import admin
from django.urls import path, re_path

from accounting import api

urlpatterns = [
    path("health/", api.health),
    path("admin/", admin.site.urls),
    path("api/auth/csrf/", api.csrf),
    path("api/auth/login/", api.sign_in),
    path("api/auth/logout/", api.sign_out),
    path("api/auth/session/", api.Session.as_view()),
    path("api/companies/", api.Companies.as_view()),
    path("api/companies/<int:company_id>/", api.CompanyDetail.as_view()),
    path("api/companies/<int:company_id>/<str:collection>/", api.Assignments.as_view()),
    path("api/companies/<int:company_id>/<str:collection>/<int:object_id>/", api.Assignments.as_view()),
    path("api/uploads/<uuid:upload_id>/", api.UploadTransfer.as_view()),
    path("api/documents/", api.Documents.as_view()),
    path("api/documents/<uuid:document_id>/", api.DocumentDetail.as_view()),
    path("api/documents/<uuid:document_id>/exclude/", api.DocumentExclusion.as_view(), {"excluded": True}),
    path("api/documents/<uuid:document_id>/restore/", api.DocumentExclusion.as_view(), {"excluded": False}),
    path("api/documents/<uuid:document_id>/<str:representation>/", api.DocumentFile.as_view()),
    path("api/packages/", api.Packages.as_view()),
    path("api/packages/preview/", api.Preview.as_view()),
    path("api/packages/<uuid:package_id>/", api.PackageDetail.as_view()),
    path("api/packages/<uuid:package_id>/<str:action>/", api.PackageDetail.as_view()),
    path("api/dispatches/", api.Dispatches.as_view()),
    path("api/dispatches/<uuid:dispatch_id>/", api.Dispatches.as_view()),
    path("api/jobs/", api.Jobs.as_view()),
    path("api/jobs/<uuid:job_id>/", api.Jobs.as_view()),
    path("api/jobs/<uuid:job_id>/<str:action>/", api.Jobs.as_view()),
    path("api/settings/<int:company_id>/mail/", api.MailSettings.as_view()),
    path("api/import-errors/<int:company_id>/", api.ImportErrors.as_view()),
    path("api/tokens/", api.Tokens.as_view()),
    path("api/tokens/<int:token_id>/", api.Tokens.as_view()),
    path("api/folders/<int:company_id>/", api.Folders.as_view()),
    path("api/schema/", api.Schema.as_view()),
    re_path(r"^(?P<resource>.*)$", api.spa),
]
