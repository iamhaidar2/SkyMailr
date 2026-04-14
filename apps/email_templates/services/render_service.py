import logging
from typing import Any

import bleach
from jinja2 import StrictUndefined, TemplateSyntaxError
from jinja2.sandbox import SandboxedEnvironment

logger = logging.getLogger(__name__)

_ALLOWED_TAGS = bleach.sanitizer.ALLOWED_TAGS | {
    "p",
    "br",
    "strong",
    "em",
    "u",
    "a",
    "ul",
    "ol",
    "li",
    "h1",
    "h2",
    "h3",
    "table",
    "tr",
    "td",
    "th",
    "thead",
    "tbody",
    "img",
    "span",
    "div",
}
_ALLOWED_ATTRS = {
    "a": ["href", "title", "style", "class"],
    "img": ["src", "alt", "width", "height", "style", "class"],
    "*": ["style", "class"],
}


class TemplateRenderError(Exception):
    pass


def _env() -> SandboxedEnvironment:
    return SandboxedEnvironment(undefined=StrictUndefined)


def render_string(template_str: str, context: dict[str, Any]) -> str:
    try:
        return _env().from_string(template_str).render(**context)
    except TemplateSyntaxError as e:
        raise TemplateRenderError(f"Invalid template syntax: {e}") from e
    except Exception as e:
        raise TemplateRenderError(str(e)) from e


def sanitize_html(html: str) -> str:
    return bleach.clean(html, tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRS, strip=True)


def render_email_version(
    *,
    subject_template: str,
    preview_template: str,
    html_template: str,
    text_template: str,
    context: dict[str, Any],
    sanitize: bool = True,
) -> dict[str, str]:
    subject = render_string(subject_template, context)
    preview = render_string(preview_template or "", context) if preview_template else ""
    html_out = render_string(html_template, context)
    text_out = render_string(text_template or "", context) if text_template else ""
    if sanitize:
        html_out = sanitize_html(html_out)
    return {
        "subject": subject.strip(),
        "preview": preview.strip(),
        "html": html_out,
        "text": text_out.strip(),
    }
