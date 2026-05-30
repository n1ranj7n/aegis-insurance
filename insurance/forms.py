"""Forms for creating/editing domain objects from the UI.

Cross-field validation lives here (e.g. a claim cannot exceed its policy's sum
insured). Per-field bounds are enforced by model validators; these forms add the
friendly, demo-appropriate guardrails on top.
"""

from datetime import date, timedelta
from decimal import Decimal

from django import forms

from .models import Claim, Policy, Policyholder

# Upper sanity bounds so the public demo can't be fed absurd figures.
MAX_SUM_INSURED = Decimal("100000000")  # ₹10 Cr
MAX_PREMIUM = Decimal("5000000")  # ₹50 L


class _DateInput(forms.DateInput):
    input_type = "date"


class PolicyholderForm(forms.ModelForm):
    class Meta:
        model = Policyholder
        fields = ["name", "email", "date_of_birth", "gender", "phone", "address"]
        widgets = {
            "date_of_birth": _DateInput(),
            "address": forms.Textarea(attrs={"rows": 2}),
        }

    def clean_date_of_birth(self):
        dob = self.cleaned_data["date_of_birth"]
        if dob > date.today():
            raise forms.ValidationError("Date of birth cannot be in the future.")
        if dob < date.today() - timedelta(days=365 * 120):
            raise forms.ValidationError("Please enter a realistic date of birth.")
        return dob


class PolicyForm(forms.ModelForm):
    class Meta:
        model = Policy
        fields = [
            "policyholder",
            "plan_type",
            "sum_insured",
            "base_premium",
            "start_date",
            "renewal_date",
        ]
        widgets = {
            "start_date": _DateInput(),
            "renewal_date": _DateInput(),
        }

    def clean_sum_insured(self):
        value = self.cleaned_data["sum_insured"]
        if value <= 0:
            raise forms.ValidationError("Sum insured must be positive.")
        if value > MAX_SUM_INSURED:
            raise forms.ValidationError("Sum insured is unrealistically large for this demo.")
        return value

    def clean_base_premium(self):
        value = self.cleaned_data["base_premium"]
        if value <= 0:
            raise forms.ValidationError("Premium must be positive.")
        if value > MAX_PREMIUM:
            raise forms.ValidationError("Premium is unrealistically large for this demo.")
        return value

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("start_date")
        renewal = cleaned.get("renewal_date")
        sum_insured = cleaned.get("sum_insured")
        base_premium = cleaned.get("base_premium")

        if start and renewal and renewal <= start:
            self.add_error("renewal_date", "Renewal date must be after the start date.")
        if sum_insured and base_premium and base_premium > sum_insured:
            self.add_error(
                "base_premium", "Premium cannot exceed the sum insured — check your figures."
            )
        return cleaned

    def save(self, commit=True):
        policy = super().save(commit=False)
        # New policies start at the base premium with a clean NCB slate.
        if policy.current_premium is None:
            policy.current_premium = policy.base_premium
        if commit:
            policy.save()
        return policy


class ClaimForm(forms.ModelForm):
    class Meta:
        model = Claim
        fields = [
            "policy",
            "claim_amount",
            "claim_type",
            "hospital_name",
            "date_of_service",
            "status",
            "notes",
        ]
        widgets = {
            "date_of_service": _DateInput(),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def clean_claim_amount(self):
        value = self.cleaned_data["claim_amount"]
        if value <= 0:
            raise forms.ValidationError("Claim amount must be positive.")
        return value

    def clean_date_of_service(self):
        dos = self.cleaned_data["date_of_service"]
        if dos > date.today() + timedelta(days=1):
            raise forms.ValidationError("Date of service cannot be in the future.")
        return dos

    def clean(self):
        cleaned = super().clean()
        policy = cleaned.get("policy")
        amount = cleaned.get("claim_amount")
        if policy and amount and amount > policy.sum_insured:
            self.add_error(
                "claim_amount",
                f"Claim amount ₹{amount:,.0f} exceeds the policy's sum insured "
                f"₹{policy.sum_insured:,.0f}.",
            )
        return cleaned
