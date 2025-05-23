# Generated by Django 4.2.9 on 2025-02-13 13:03

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('quotes', '0002_quoterequest_email_body_quoterequest_email_sender_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='quoterequest',
            name='email_body',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='quoterequest',
            name='email_sender',
            field=models.EmailField(blank=True, max_length=254, null=True),
        ),
        migrations.AlterField(
            model_name='quoterequest',
            name='email_subject',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]
