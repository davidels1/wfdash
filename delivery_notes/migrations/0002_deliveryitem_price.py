# Generated by Django 4.2.9 on 2025-03-30 18:04

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('delivery_notes', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='deliveryitem',
            name='price',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
        ),
    ]
