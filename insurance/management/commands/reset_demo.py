"""Reset the public demo: truncate all domain tables and re-seed.

Intended to run nightly (cron / Render Cron Job) so the deployed demo always
returns to a clean, populated state. See README → "Scheduling the nightly reset".

    python manage.py reset_demo
"""

from django.core.management import call_command
from django.core.management.base import BaseCommand

from insurance.services import truncate_domain_data


class Command(BaseCommand):
    help = "Truncate all domain tables and re-run the demo seed (nightly reset)."

    def handle(self, *args, **options):
        self.stdout.write("Resetting demo environment...")
        truncate_domain_data()
        # seed_demo also wipes (idempotent) and recreates the demo user + data.
        call_command("seed_demo")
        self.stdout.write(self.style.SUCCESS("Demo environment reset."))
