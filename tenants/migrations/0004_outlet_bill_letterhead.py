from django.db import migrations, models


class Migration(migrations.Migration):
    """GSTIN, mobile, email and bill terms on outlets, printed on credit bills."""

    dependencies = [
        ("tenants", "0003_subscriptionrenewal"),
    ]

    operations = [
        migrations.AddField(
            model_name="outlet",
            name="gstin",
            field=models.CharField(blank=True, default="", max_length=15, verbose_name="GSTIN"),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="outlet",
            name="phone",
            field=models.CharField(blank=True, default="", max_length=20, verbose_name="mobile"),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="outlet",
            name="email",
            field=models.EmailField(blank=True, default="", max_length=254),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="outlet",
            name="bill_terms",
            field=models.TextField(blank=True, default="", verbose_name="terms and conditions on bills",
                                   help_text="Printed at the bottom of every credit bill. One condition per line."),
            preserve_default=False,
        ),
    ]
