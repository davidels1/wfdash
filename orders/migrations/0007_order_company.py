# Generated by Django 4.2.9 on 2025-02-11 10:27

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('wfdash', '0003_companydetails'),
        ('orders', '0006_remove_purchaseorder_notes_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='company',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='wfdash.company'),
            preserve_default=False,
        ),
    ]
