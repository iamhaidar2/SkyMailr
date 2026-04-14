import json

from django import template

register = template.Library()


@register.filter
def as_pretty_json(value):
    try:
        return json.dumps(value, indent=2, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)
