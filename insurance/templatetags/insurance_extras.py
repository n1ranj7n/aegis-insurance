"""Template helpers: Indian-rupee formatting and status → badge classes."""

from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


def _group_indian(integer_str: str) -> str:
    """Group an integer string with the Indian system: 12,34,567."""
    if len(integer_str) <= 3:
        return integer_str
    head, tail = integer_str[:-3], integer_str[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts) + "," + tail


@register.filter
def inr(value):
    """Format a number as ₹ with Indian digit grouping, no decimals."""
    try:
        number = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return value
    sign = "-" if number < 0 else ""
    whole = f"{abs(number):.0f}"
    return f"{sign}₹{_group_indian(whole)}"


@register.filter
def inr_compact(value):
    """Short Indian form: ₹3.0L, ₹50L, ₹1.2Cr."""
    try:
        number = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return value
    n = abs(number)
    if n >= 10_000_000:
        return f"₹{n / Decimal(10_000_000):.2f}Cr"
    if n >= 100_000:
        return f"₹{n / Decimal(100_000):.1f}L"
    if n >= 1_000:
        return f"₹{n / Decimal(1_000):.0f}K"
    return f"₹{n:.0f}"


POLICY_STATUS_BADGE = {"active": "green", "lapsed": "red"}
CLAIM_STATUS_BADGE = {
    "submitted": "blue",
    "approved": "green",
    "settled": "green",
    "rejected": "red",
}


@register.filter
def policy_badge(status):
    return POLICY_STATUS_BADGE.get(status, "grey")


@register.filter
def claim_badge(status):
    return CLAIM_STATUS_BADGE.get(status, "grey")
