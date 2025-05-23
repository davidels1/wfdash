# Generated by Django 4.2.9 on 2025-04-08 14:55

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0017_order_potential_quote_and_more"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="order",
            index=models.Index(fields=["status"], name="orders_orde_status_c6dd84_idx"),
        ),
        migrations.AddIndex(
            model_name="order",
            index=models.Index(
                fields=["created_at"], name="orders_orde_created_0e92de_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="order",
            index=models.Index(fields=["rep"], name="orders_orde_rep_id_26ac83_idx"),
        ),
        migrations.AddIndex(
            model_name="order",
            index=models.Index(
                fields=["company"], name="orders_orde_company_c4eb9e_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="order",
            index=models.Index(
                fields=["status", "created_at"], name="orders_orde_status_25e057_idx"
            ),
        ),
    ]
