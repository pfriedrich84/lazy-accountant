from django.db import migrations, models
from django.db.models import F


def backfill(apps, schema_editor):
    apps.get_model("accounting", "PaymentAllocation").objects.update(bank_amount=F("amount"))


class Migration(migrations.Migration):
    dependencies = [("accounting", "0012_bankidentityresolution_and_more")]
    operations = [
        migrations.AddField(
            model_name="paymentallocation",
            name="bank_amount",
            field=models.DecimalField(max_digits=20, decimal_places=6, null=True),
        ),
        migrations.RunPython(backfill, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="paymentallocation",
            name="bank_amount",
            field=models.DecimalField(max_digits=20, decimal_places=6),
        ),
        migrations.AddConstraint(
            model_name="paymentallocation",
            constraint=models.CheckConstraint(
                condition=models.Q(bank_amount__gt=0), name="positive_bank_allocation"
            ),
        ),
    ]
