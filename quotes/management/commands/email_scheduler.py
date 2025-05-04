from django.core.management.base import BaseCommand
from django.conf import settings
import time
import subprocess
import sys
from datetime import datetime

class Command(BaseCommand):
    help = 'Process emails continuously every minute'

    def handle(self, *args, **options):
        self.stdout.write('Starting email processing loop...')
        
        try:
            while True:
                self.stdout.write(f'Processing emails at {datetime.now()}')
                result = subprocess.run([sys.executable, "manage.py", "process_emails"], 
                                        capture_output=True, text=True)
                self.stdout.write(f'Completed with output:\n{result.stdout}')
                if result.stderr:
                    self.stdout.write(f'Errors: {result.stderr}')
                
                # Wait for 60 seconds before next check
                time.sleep(60)
                
        except KeyboardInterrupt:
            self.stdout.write(self.style.SUCCESS('Email processing stopped'))