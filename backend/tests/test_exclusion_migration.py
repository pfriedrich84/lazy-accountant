import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True)
def test_exclusion_migration_preserves_legacy_documents_revisions_and_snapshots():
    before = [("accounting", "0004_alter_document_related")]
    executor = MigrationExecutor(connection)
    latest = executor.loader.graph.leaf_nodes()
    executor.migrate(before)
    try:
        apps = executor.loader.project_state(before).apps
        User = apps.get_model("auth", "User")
        Company = apps.get_model("accounting", "Company")
        Document = apps.get_model("accounting", "Document")
        Revision = apps.get_model("accounting", "Revision")
        Package = apps.get_model("accounting", "Package")
        user = User.objects.create(username="migration-user")
        company = Company.objects.create(name="Legacy", folder="Legacy")
        doc = Document.objects.create(
            inbox_owner=user,
            company=company,
            original_name="image001.png",
            original_path="_originals/legacy.png",
            sha256="a" * 64,
            size=12,
            media_type="image/png",
            status="review",
            issues=["legacy issue"],
        )
        historical = {"status": "review", "version": 1}
        Revision.objects.create(
            document=doc, version=1, base_version=0, actor=user, source="upload", snapshot=historical
        )
        snapshot = {"documents": [], "excluded": [{"reason": "legacy issue"}], "unassigned_inbox": []}
        package = Package.objects.create(
            company=company,
            periods=["2026-10"],
            version=1,
            snapshot=snapshot,
            path="_packages/legacy.zip",
            sha256="b" * 64,
            size=123,
            actor=user,
            idempotency_key="legacy",
        )
        executor = MigrationExecutor(connection)
        executor.migrate(latest)
        apps = executor.loader.project_state(latest).apps
        migrated = apps.get_model("accounting", "Document").objects.get(id=doc.id)
        assert not migrated.is_excluded and migrated.exclusion_reason == ""
        assert migrated.excluded_by_id is migrated.excluded_at is None
        assert migrated.version == 1 and migrated.issues == ["legacy issue"]
        revision = apps.get_model("accounting", "Revision").objects.get(document_id=doc.id)
        assert revision.reason == "" and revision.snapshot == historical
        frozen = apps.get_model("accounting", "Package").objects.get(id=package.id)
        assert frozen.snapshot == snapshot and frozen.sha256 == "b" * 64
    finally:
        MigrationExecutor(connection).migrate(latest)
