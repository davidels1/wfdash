import re
from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter(name="multiply")
def multiply(value, arg):
    try:
        return float(value or 0) * float(arg or 0)
    except (ValueError, TypeError):
        return 0


@register.filter
def endswith(value, extensions):
    """Check if value ends with any of the given extensions"""
    if not value:
        return False
    extensions = extensions.split(",")
    return any(value.lower().endswith(ext.strip().lower()) for ext in extensions)


@register.filter
def split_notes(notes_text):
    """Split notes into individual entries based on problem reports or line breaks"""
    if not notes_text:
        return []

    # First split by problem reports
    pattern = r"(PROBLEM REPORTED \(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\):.*?)(?=PROBLEM REPORTED \(|\Z)"
    parts = re.split(pattern, notes_text, flags=re.DOTALL)

    # Filter out empty strings and combine parts properly
    result = []
    i = 0
    while i < len(parts):
        if "PROBLEM REPORTED" in parts[i]:
            result.append(parts[i].strip())
        elif parts[i].strip():  # Non-empty regular note
            # Split regular notes by newlines
            for line in parts[i].strip().split("\n"):
                if line.strip():
                    result.append(line.strip())
        i += 1

    return result


@register.filter
def extract_timestamp(problem_text):
    """Extract timestamp from problem report text"""
    match = re.search(r"PROBLEM REPORTED \(([^)]+)\):", problem_text)
    if match:
        return match.group(1)
    return ""


@register.filter
def problem_content(problem_text):
    """Extract content from problem report text"""
    match = re.search(r"PROBLEM REPORTED \([^)]+\):(.*)", problem_text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return problem_text


@register.filter
def filter_markup(items, max_value):
    """Filter items with markup below or equal to max_value"""
    return [
        item for item in items if item.markup is not None and item.markup <= max_value
    ]


@register.filter
def filter_markup_range(items, range_values):
    """Filter items with markup between min_value and max_value
    Usage: {{ items|filter_markup_range:'16,30' }}
    """
    try:
        min_value, max_value = map(float, range_values.split(","))
        return [
            item
            for item in items
            if item.markup is not None and min_value <= item.markup <= max_value
        ]
    except (ValueError, AttributeError):
        return []


@register.filter
def filter_markup_above(items, min_value):
    """Filter items with markup above min_value"""
    return [
        item for item in items if item.markup is not None and item.markup > min_value
    ]
