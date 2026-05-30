"""Run the renewal / premium recalculation for one or more policies.

    python manage.py run_renewal --policy POL-2026-00001
    python manage.py run_renewal --all

This exposes the same engine as the dashboard button and admin action from the
command line — useful for cron-driven renewals or quick demos.
"""

from django.core.management.base import BaseCommand, CommandError

from insurance.models import Policy
from insurance.services import run_renewal


class Command(BaseCommand):
    help = "Simulate a renewal (NCB recalculation) for a policy or all policies."

    def add_arguments(self, parser):
        parser.add_argument(
            "--policy",
            dest="policy_number",
            help="Policy number to renew, e.g. POL-2026-00001.",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Run renewal for every policy.",
        )

    def handle(self, *args, **options):
        if options["all"]:
            policies = list(Policy.objects.all())
        elif options["policy_number"]:
            try:
                policies = [Policy.objects.get(policy_number=options["policy_number"])]
            except Policy.DoesNotExist:
                raise CommandError(f"No policy with number {options['policy_number']!r}.")
        else:
            raise CommandError("Provide --policy <number> or --all.")

        for policy in policies:
            history = run_renewal(policy)
            self.stdout.write(
                f"{policy.policy_number}: Rs {history.previous_premium:,.0f} -> "
                f"Rs {history.new_premium:,.0f} "
                f"({history.discount_pct_applied}% NCB, streak {policy.no_claim_streak})"
            )
        self.stdout.write(self.style.SUCCESS(f"Renewed {len(policies)} policy(ies)."))
