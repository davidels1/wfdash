from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone
from django.conf import settings
from datetime import timedelta
from quotes.models import QuoteRequest
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Send daily quote status reports'

    def handle(self, *args, **kwargs):
        try:
            # Get stale quotes (not updated for 3 days)
            stale_cutoff = timezone.now() - timedelta(days=3)
            stale_quotes = QuoteRequest.objects.filter(
                updated_at__lt=stale_cutoff,
                status__in=['new', 'in_progress']
            )

            # Get problem quotes
            problem_quotes = QuoteRequest.objects.filter(
                status='problem'
            )

            # Prepare email content
            context = {
                'stale_quotes': stale_quotes,
                'problem_quotes': problem_quotes,
                'report_date': timezone.now().date()
            }
            
            html_content = render_to_string('quotes/email/daily_report.html', context)

            # Send email
            send_mail(
                subject=f'Daily Quote Report - {timezone.now().date()}',
                message='Please view this email in HTML format',
                from_email=settings.REPORT_SENDER_EMAIL,
                recipient_list=settings.REPORT_RECIPIENT_LIST,
                html_message=html_content,
                fail_silently=False
            )

            self.stdout.write(
                self.style.SUCCESS('Successfully sent daily report email')
            )
            
        except Exception as e:
            logger.error(f'Failed to send daily report: {str(e)}')
            self.stdout.write(
                self.style.ERROR(f'Error sending report: {str(e)}')
            )