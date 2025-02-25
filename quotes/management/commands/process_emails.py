from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils import timezone
from django.contrib.auth import get_user_model
import email
import imaplib
import logging
from quotes.models import QuoteRequest, QuoteItem
from wfdash.models import Customers
import os

User = get_user_model()

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Process emails into quote requests'

    def handle(self, *args, **kwargs):
        try:
            # Get default rep for initial assignment
            default_rep = User.objects.filter(is_staff=True).first()
            if not default_rep:
                self.stdout.write(self.style.ERROR('No staff user found to assign as rep'))
                return

            # Connect to email
            mail = imaplib.IMAP4_SSL('imap.gmail.com')
            mail.login(settings.EMAIL_HOST_USER, settings.EMAIL_HOST_PASSWORD)
            mail.select('inbox')

            # Search for unread emails
            _, messages = mail.search(None, 'UNSEEN')
            
            if not messages[0]:
                self.stdout.write('No new emails found')
                return

            for msg_id in messages[0].split():
                try:
                    _, msg_data = mail.fetch(msg_id, '(RFC822)')
                    email_body = email.message_from_bytes(msg_data[0][1])

                    # Extract email details
                    sender_email = email_body['from'].split('<')[-1].strip('>')
                    subject = email_body['subject']
                    
                    # Create or get customer
                    company_name = sender_email.split('@')[1].split('.')[0].title()
                    customer, created = Customers.objects.get_or_create(
                        email=sender_email,
                        defaults={'company': company_name}
                    )

                    # Create quote request
                    quote = QuoteRequest.objects.create(
                        customer=customer,
                        quote_number=f"RFQ{QuoteRequest.objects.count() + 1:06d}",  # RFQ prefix for email quotes
                        description=subject,
                        notes=f"""
EMAIL QUOTE REQUEST
------------------
From: {sender_email}
Subject: {subject}
Date: {email_body['date']}

Message:
{self._get_email_body(email_body)}
                        """.strip(),
                        status='new',
                        rep=default_rep,
                        email_sender=sender_email,
                        email_subject=subject,
                        email_body=self._get_email_body(email_body),
                        has_attachments=False  # Will be updated if attachments found
                    )

                    # Create initial quote item for the request
                    QuoteItem.objects.create(
                        quote=quote,
                        description=f"Items from email request: {subject}",
                        quantity=1,
                        notes="Please review email content and update details accordingly"
                    )

                    # Process attachments
                    self._save_attachments(email_body, quote)

                    self.stdout.write(
                        self.style.SUCCESS(
                            f'Created quote request {quote.quote_number} from {sender_email}'
                        )
                    )

                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(f'Error processing email {msg_id}: {str(e)}')
                    )
                    continue

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error: {str(e)}'))

    def _get_email_body(self, email_message):
        if email_message.is_multipart():
            for part in email_message.walk():
                if part.get_content_type() == "text/plain":
                    return part.get_payload(decode=True).decode()
        return email_message.get_payload(decode=True).decode()

    def _save_attachments(self, email_message, quote):
        attachment_count = 0
        for part in email_message.walk():
            if part.get_content_maintype() == 'multipart':
                continue
            if part.get('Content-Disposition') is None:
                continue

            filename = part.get_filename()
            if filename:
                # Save attachment using QuoteAttachment model
                content = part.get_payload(decode=True)
                from django.core.files.base import ContentFile
                from quotes.models import QuoteAttachment
                
                attachment = QuoteAttachment.objects.create(
                    quote=quote,
                    filename=filename
                )
                attachment.file.save(filename, ContentFile(content))
                attachment_count += 1

        if attachment_count > 0:
            quote.has_attachments = True
            quote.notes += f"\n\nAttachments: {attachment_count} file(s) attached"
            quote.save()