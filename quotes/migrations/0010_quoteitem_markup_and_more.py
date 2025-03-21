# Generated by Django 4.2.9 on 2025-02-17 23:25

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('quotes', '0009_alter_quoterequest_company_letterhead'),
    ]

    operations = [
        migrations.AddField(
            model_name='quoteitem',
            name='markup',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
        ),
        migrations.AlterField(
            model_name='quoterequest',
            name='company_letterhead',
            field=models.CharField(choices=[('CNL', 'CNL'), ('ISHERWOOD', 'Isherwood')], default='CNL', max_length=20),
        ),
    ]
