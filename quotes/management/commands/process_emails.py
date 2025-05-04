from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils import timezone
from django.contrib.auth import get_user_model
import email
import imaplib
import logging
import traceback
from quotes.models import QuoteRequest, QuoteItem, QuoteAttachment
from wfdash.models import Customers
import os
from quotes.utils import generate_unique_quote_number
from django.db import IntegrityError
from django.core.files.base import ContentFile

User = get_user_model()

# Set up logger
logger = logging.getLogger("quotes.management")


class Command(BaseCommand):
    help = "Process emails into quote requests"

    def handle(self, *args, **kwargs):
        logger.info("Starting email processing job")
        try:
            # Get default rep for initial assignment
            default_rep = User.objects.filter(is_staff=True).first()
            if not default_rep:
                logger.error("No staff user found to assign as rep")
                return

            # Connect to email
            try:
                if "gmail" in settings.EMAIL_HOST.lower():
                    mail = imaplib.IMAP4_SSL("imap.gmail.com")
                elif "wfsales.co.za" in settings.EMAIL_HOST.lower():
                    mail = imaplib.IMAP4_SSL("mail.wfsales.co.za")
                else:
                    mail = imaplib.IMAP4_SSL(settings.EMAIL_HOST)

                logger.info(f"Connecting to mail server: {settings.EMAIL_HOST}")
                mail.login(settings.EMAIL_HOST_USER, settings.EMAIL_HOST_PASSWORD)
                mail.select("inbox")
                logger.info(f"Successfully connected to {settings.EMAIL_HOST_USER}")
            except Exception as e:
                logger.error(f"Failed to connect to mail server: {str(e)}")
                return

            # Search for unread emails
            _, messages = mail.search(None, "UNSEEN")

            if not messages[0]:
                logger.info("No new emails found")
                return

            for msg_id in messages[0].split():
                try:
                    _, msg_data = mail.fetch(msg_id, "(RFC822)")
                    email_body = email.message_from_bytes(msg_data[0][1])

                    # Extract email details
                    try:
                        from_header = email_body["from"]
                        if "<" in from_header:
                            sender_email = from_header.split("<")[-1].strip(">")
                        else:
                            sender_email = from_header.strip()

                        subject = email_body["subject"]
                        if not subject:
                            subject = "[No Subject]"
                    except Exception as e:
                        logger.error(f"Error extracting email headers: {str(e)}")
                        sender_email = "unknown@example.com"
                        subject = "Email parsing error"

                    # Create or get customer - handle duplicates
                    company_name = sender_email.split("@")[1].split(".")[0].title()
                    try:
                        # Try to get a specific customer first
                        customer = Customers.objects.filter(email=sender_email).first()
                        if not customer:
                            # Create new if doesn't exist
                            logger.info(
                                f"Creating new customer with email {sender_email}"
                            )
                            customer = Customers.objects.create(
                                email=sender_email, company=company_name
                            )
                    except Exception as e:
                        logger.error(f"Error finding/creating customer: {str(e)}")
                        # Create a new generic customer as fallback
                        unique_suffix = timezone.now().strftime("%Y%m%d%H%M%S")
                        customer = Customers.objects.create(
                            email=f"{unique_suffix}-{sender_email}",
                            company=f"{company_name} (Auto-created)",
                        )

                    # Create quote request
                    max_attempts = 3
                    for attempt in range(max_attempts):
                        try:
                            quote = QuoteRequest.objects.create(
                                customer=customer,
                                quote_number=generate_unique_quote_number(),
                                description=subject,
                                notes=f"""
EMAIL QUOTE REQUEST
------------------
From: {sender_email}
Subject: {subject}
Date: {email_body["date"]}
Received: {timezone.now().strftime("%Y-%m-%d %H:%M:%S")}

Message:
{self._get_email_body(email_body)}
                                """.strip(),
                                status="new",
                                rep=default_rep,
                                user=default_rep,
                                email_sender=sender_email,
                                email_subject=subject,
                                email_body=self._get_email_body(email_body),
                                has_attachments=False,
                            )
                            break
                        except IntegrityError:
                            if attempt == max_attempts - 1:
                                logger.error(
                                    f"Failed to create quote after {max_attempts} attempts"
                                )
                                raise

                    # Create initial quote item for the request
                    QuoteItem.objects.create(
                        quote=quote,
                        description=f"Items from email request: {subject}",
                        quantity=1,
                        notes="Please review email content and update details accordingly",
                    )

                    # Process attachments
                    self._save_attachments(email_body, quote)

                    logger.info(
                        f"Created quote request {quote.quote_number} from {sender_email}"
                    )

                except Exception as e:
                    logger.error(f"Error processing email {msg_id}: {str(e)}")
                    logger.error(traceback.format_exc())
                    continue

        except Exception as e:
            logger.error(f"Error in email processing: {str(e)}")
            logger.error(traceback.format_exc())

    def _get_email_body(self, email_message):
        if email_message.is_multipart():
            for part in email_message.walk():
                if part.get_content_type() == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload is not None:
                        try:
                            # Try UTF-8 first
                            return payload.decode("utf-8")
                        except UnicodeDecodeError:
                            try:
                                # Fall back to Latin-1
                                return payload.decode("latin-1")
                            except:
                                # Last resort - ignore errors
                                return payload.decode("utf-8", errors="ignore")
                    return "[Empty email body]"

        payload = email_message.get_payload(decode=True)
        if payload is not None:
            try:
                # Try UTF-8 first
                return payload.decode("utf-8")
            except UnicodeDecodeError:
                try:
                    # Fall back to Latin-1
                    return payload.decode("latin-1")
                except:
                    # Last resort - ignore errors
                    return payload.decode("utf-8", errors="ignore")
        return "[Empty email body]"

    def _save_attachments(self, email_message, quote):
        attachment_count = 0
        for part in email_message.walk():
            if part.get_content_maintype() == "multipart":
                continue
            if part.get("Content-Disposition") is None:
                continue

            filename = part.get_filename()
            if filename:
                # Save attachment using QuoteAttachment model
                content = part.get_payload(decode=True)

                attachment = QuoteAttachment.objects.create(
                    quote=quote, filename=filename
                )
                attachment.file.save(filename, ContentFile(content))
                attachment_count += 1

        if attachment_count > 0:
            quote.has_attachments = True
            quote.notes += f"\n\nAttachments: {attachment_count} file(s) attached"
            quote.save()
            logger.info(
                f"Saved {attachment_count} attachments for quote {quote.quote_number}"
            )
