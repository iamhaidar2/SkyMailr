"""Merge plain-text edits into existing HTML when the HTML field is unchanged (save version)."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Comment, NavigableString

_SKIP_PARENTS = frozenset({"script", "style", "textarea"})


def _norm_ws(s: str) -> str:
    return re.sub(r"[ \t\r\n]+", " ", (s or "").strip())


def _collapse_text(s: str) -> str:
    """Compare HTML-derived text to plain without requiring matching whitespace."""
    return re.sub(r"\s+", "", (s or ""))


def _text_nodes(soup: BeautifulSoup) -> list[NavigableString]:
    out: list[NavigableString] = []
    for t in soup.find_all(string=True):
        if isinstance(t, Comment):
            continue
        if not isinstance(t, NavigableString):
            continue
        p = t.parent
        if not p or p.name in _SKIP_PARENTS:
            continue
        out.append(t)
    return out


def plain_text_from_html(html: str) -> str:
    """Visible text from HTML, newlines between block elements (Jinja stays as text)."""
    raw = html or ""
    if not raw.strip():
        return ""
    soup = BeautifulSoup(raw, "html.parser")
    text = soup.get_text("\n")
    return text.replace("\r\n", "\n").strip("\n")


def fallback_plain_to_minimal_html(plain: str) -> str:
    """
    When structured merge cannot apply, wrap each line in <p> with raw text (Jinja-friendly).
    Does not HTML-escape content so {{ }} and {% %} remain valid for rendering.
    """
    p = (plain or "").replace("\r\n", "\n")
    soup = BeautifulSoup("", "html.parser")
    container = soup.new_tag("div")
    for line in p.split("\n"):
        para = soup.new_tag("p")
        para.append(NavigableString(line))
        container.append(para)
    return str(container)


def merge_plain_into_html_if_unchanged(
    latest_html: str,
    posted_html: str,
    latest_text: str,
    posted_text: str,
) -> str:
    """
    When the user leaves the HTML textarea identical to the last saved version but edits
    plain text, push the new plain text into the existing HTML tree (tags preserved).

    If the HTML field was edited, or we cannot map plain text to text nodes safely, returns
    ``posted_html`` unchanged.
    """
    lh = (latest_html or "").strip()
    ph = (posted_html or "").strip()
    if ph != lh:
        return posted_html or ""
    lt = (latest_text or "").replace("\r\n", "\n")
    pt = (posted_text or "").replace("\r\n", "\n")
    if pt == lt:
        return posted_html or ""

    soup = BeautifulSoup(latest_html or "", "html.parser")
    nodes = _text_nodes(soup)
    if not nodes:
        return posted_html or ""

    joined = "".join(str(n) for n in nodes)
    if _collapse_text(joined) != _collapse_text(lt):
        return posted_html or ""

    lines_new = pt.split("\n")

    if len(nodes) == 1:
        nodes[0].replace_with(pt)
        return str(soup)

    if len(lines_new) == len(nodes):
        for node, line in zip(nodes, lines_new, strict=True):
            node.replace_with(line)
        return str(soup)

    return posted_html or ""


def reconcile_template_bodies(
    latest_html: str,
    latest_text: str,
    posted_html: str,
    posted_text: str,
) -> tuple[str, str]:
    """
    Produce a consistent (html_template, text_template) pair on Save version.

    - If the HTML field differs from the last saved HTML, HTML wins; plain is derived from HTML.
    - If HTML is unchanged, merge plain into the existing HTML structure when possible; otherwise
      wrap plain in minimal paragraphs. Stored plain is always ``plain_text_from_html(html_out)``.
    """
    lh = (latest_html or "").strip()
    ph = (posted_html or "").strip()
    lt_norm = (latest_text or "").replace("\r\n", "\n")
    pt_norm = (posted_text or "").replace("\r\n", "\n")

    if ph != lh:
        html_out = posted_html or ""
        text_out = plain_text_from_html(html_out)
        return html_out, text_out

    merged = merge_plain_into_html_if_unchanged(
        latest_html or "",
        posted_html or "",
        latest_text or "",
        posted_text or "",
    )
    posted_cmp = posted_html or ""
    plain_changed = pt_norm != lt_norm
    if merged == posted_cmp and plain_changed:
        html_out = fallback_plain_to_minimal_html(posted_text or "")
    else:
        html_out = merged

    text_out = plain_text_from_html(html_out)
    return html_out, text_out
