# Generated by Django 4.2.9 on 2025-02-13 21:21

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('driver_list', '0005_alter_collection_planned_date'),
    ]

    operations = [
        migrations.AddField(
            model_name='collection',
            name='quantity',
            field=models.DecimalField(decimal_places=2, default=1, max_digits=10),
            preserve_default=False,
        ),
    ]
