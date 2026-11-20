import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "leaf", ["0009_merge_document_security", "0009_merge_0007_document_security_0008_merge_20261119_2155"]
)
def test_control_upgrade_preserves_either_existing_merge_path(leaf):
    executor = MigrationExecutor(connection)
    latest = executor.loader.graph.leaf_nodes()
    before = [("accounting", leaf)]
    executor.migrate(before)
    try:
        apps = executor.loader.project_state(before).apps
        User = apps.get_model("auth", "User")
        Company = apps.get_model("accounting", "Company")
        Account = apps.get_model("accounting", "Account")
        BankTransaction = apps.get_model("accounting", "BankTransaction")
        Receipt = apps.get_model("accounting", "IdempotencyRecord")
        user = User.objects.create(username="synthetic-control-upgrade")
        company = Company.objects.create(name="Synthetic", folder="Synthetic")
        account = Account.objects.create(
            company=company, name="Synthetic Bank", kind="bank", identifier="synthetic"
        )
        tx = BankTransaction.objects.create(
            company=company,
            account=account,
            identity="synthetic",
            amount="120",
            currency="EUR",
            direction="CRDT",
            booked=True,
        )
        tx.refresh_from_db()
        Receipt.objects.create(
            actor=user,
            operation="synthetic",
            key="old",
            request_hash="a" * 64,
            result={"transaction_ids": [str(tx.id)]},
        )
        executor = MigrationExecutor(connection)
        executor.migrate(latest)
        apps = executor.loader.project_state(latest).apps
        assert apps.get_model("accounting", "BankTransaction").objects.get(id=tx.id).amount == tx.amount
        assert apps.get_model("accounting", "IdempotencyRecord").objects.get(key="old").result == {
            "transaction_ids": [str(tx.id)]
        }
        for model in [
            "BankAutomationPolicy",
            "BankMonthCoverage",
            "BankCoverageSource",
            "BankControlEvent",
            "PaymentAllocation",
        ]:
            assert apps.get_model("accounting", model).objects.count() == 0
    finally:
        MigrationExecutor(connection).migrate(latest)
