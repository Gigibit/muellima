from decimal import Decimal

from django import template

register = template.Library()


@register.filter
def euros(cents):
    try:
        return f"{Decimal(cents or 0) / Decimal(100):.2f}".replace(".", ",")
    except (TypeError, ValueError):
        return "0,00"


@register.filter
def firstword(value):
    words = str(value or "").strip().split()
    return words[0] if words else ""
