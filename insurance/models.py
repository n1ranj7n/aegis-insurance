"""Domain models for the Aegis health-insurance demo.

Four tables make up the domain:

* :class:`Policyholder` — the insured customer.
* :class:`Policy`       — a health policy held by a policyholder.
* :class:`Claim`        — a claim filed against a policy.
* :class:`PremiumHistory` — an append-only audit row written on every premium
  recalculation (see ``insurance.services.recalculate_premium``).
"""

from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class Gender(models.TextChoices):
    MALE = "M", "Male"
    FEMALE = "F", "Female"
    OTHER = "O", "Other"


class PlanType(models.TextChoices):
    INDIVIDUAL = "individual", "Individual"
    FAMILY_FLOATER = "family_floater", "Family Floater"
    SENIOR_CITIZEN = "senior_citizen", "Senior Citizen"


class PolicyStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    LAPSED = "lapsed", "Lapsed"


class ClaimType(models.TextChoices):
    HOSPITALIZATION = "hospitalization", "Hospitalization"
    DAY_CARE = "day_care", "Day Care"
    OUTPATIENT = "outpatient", "Outpatient"
    CRITICAL_ILLNESS = "critical_illness", "Critical Illness"


class ClaimStatus(models.TextChoices):
    SUBMITTED = "submitted", "Submitted"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    SETTLED = "settled", "Settled"


# Claim statuses that count as "a claim happened in this period" for the
# No-Claim-Bonus engine. Submitted/Rejected do NOT break the streak.
CLAIM_AGAINST_STREAK = {ClaimStatus.APPROVED, ClaimStatus.SETTLED}


class Policyholder(models.Model):
    name = models.CharField(max_length=120)
    email = models.EmailField(unique=True)
    date_of_birth = models.DateField()
    gender = models.CharField(max_length=1, choices=Gender.choices)
    phone = models.CharField(max_length=20)
    address = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    @property
    def age(self) -> int | None:
        if not self.date_of_birth:
            return None
        today = timezone.localdate()
        return (
            today.year
            - self.date_of_birth.year
            - ((today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day))
        )


class Policy(models.Model):
    policyholder = models.ForeignKey(
        Policyholder, on_delete=models.CASCADE, related_name="policies"
    )
    policy_number = models.CharField(max_length=20, unique=True, editable=False, blank=True)
    plan_type = models.CharField(max_length=20, choices=PlanType.choices)

    sum_insured = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))]
    )
    base_premium = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))]
    )
    current_premium = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))]
    )

    # Number of consecutive claim-free renewal periods. Drives the NCB discount.
    no_claim_streak = models.PositiveIntegerField(default=0)

    status = models.CharField(
        max_length=10, choices=PolicyStatus.choices, default=PolicyStatus.ACTIVE
    )
    start_date = models.DateField()
    renewal_date = models.DateField()

    class Meta:
        ordering = ["-start_date", "policy_number"]
        verbose_name_plural = "policies"

    def __str__(self) -> str:
        return f"{self.policy_number} · {self.policyholder.name}"

    def save(self, *args, **kwargs):
        if self.current_premium is None:
            self.current_premium = self.base_premium
        super().save(*args, **kwargs)
        if not self.policy_number:
            # Readable, stable number derived from the primary key.
            self.policy_number = f"POL-{self.start_date.year}-{self.pk:05d}"
            super().save(update_fields=["policy_number"])

    @property
    def discount_pct_applied(self) -> Decimal:
        """Current discount off base premium, in percent (0–25)."""
        if not self.base_premium:
            return Decimal("0")
        saved = self.base_premium - self.current_premium
        return (saved / self.base_premium * Decimal("100")).quantize(Decimal("0.1"))

    @property
    def annual_savings(self) -> Decimal:
        return (self.base_premium - self.current_premium).quantize(Decimal("0.01"))

    @property
    def is_active(self) -> bool:
        return self.status == PolicyStatus.ACTIVE


class Claim(models.Model):
    policy = models.ForeignKey(Policy, on_delete=models.CASCADE, related_name="claims")
    claim_number = models.CharField(max_length=20, unique=True, editable=False, blank=True)
    claim_amount = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))]
    )
    claim_type = models.CharField(max_length=20, choices=ClaimType.choices)
    hospital_name = models.CharField(max_length=160, blank=True)
    date_of_service = models.DateField()
    status = models.CharField(
        max_length=12, choices=ClaimStatus.choices, default=ClaimStatus.SUBMITTED
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at", "claim_number"]

    def __str__(self) -> str:
        return f"{self.claim_number} · {self.get_claim_type_display()}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.claim_number:
            year = self.date_of_service.year if self.date_of_service else timezone.now().year
            self.claim_number = f"CLM-{year}-{self.pk:05d}"
            super().save(update_fields=["claim_number"])

    @property
    def counts_against_streak(self) -> bool:
        return self.status in CLAIM_AGAINST_STREAK


class PremiumHistory(models.Model):
    """Append-only audit of every premium recalculation."""

    policy = models.ForeignKey(
        Policy, on_delete=models.CASCADE, related_name="premium_history"
    )
    effective_date = models.DateField(default=timezone.localdate)
    previous_premium = models.DecimalField(max_digits=10, decimal_places=2)
    new_premium = models.DecimalField(max_digits=10, decimal_places=2)
    discount_pct_applied = models.DecimalField(max_digits=5, decimal_places=2)
    reason = models.CharField(max_length=255)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-effective_date", "-created_at"]
        verbose_name_plural = "premium history"

    def __str__(self) -> str:
        return f"{self.policy.policy_number} → ₹{self.new_premium} ({self.discount_pct_applied}% off)"
