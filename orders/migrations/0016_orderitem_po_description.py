# Generated by Django 4.2.9 on 2025-03-04 23:39

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0015_order_quote_order_quote_match_confidence_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="orderitem",
            name="po_description",
            field=models.CharField(
                blank=True,
                help_text="Description to use on the purchase order",
                max_length=255,
            ),
        ),
    ]
