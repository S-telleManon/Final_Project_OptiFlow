from django import template

register = template.Library()

@register.filter
def index(sequence, i):
    """Return the item at position i in a list (0-based)."""
    try:
        return sequence[i]
    except (IndexError, TypeError):
        return None