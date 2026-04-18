"""Tests for merging plain-text edits into unchanged HTML and full reconcile on save."""

from apps.email_templates.services.html_plain_sync import (
    merge_plain_into_html_if_unchanged,
    plain_text_from_html,
    reconcile_template_bodies,
)


def test_returns_posted_html_when_html_field_changed():
    old_html = "<p>Old</p>"
    new_html = "<p>New</p>"
    assert (
        merge_plain_into_html_if_unchanged(old_html, new_html, "Old", "New text") == new_html
    )


def test_single_text_node_updates_from_plain():
    html = "<p>Hello world</p>"
    new_plain = "Hello there"
    out = merge_plain_into_html_if_unchanged(html, html, "Hello world", new_plain)
    assert "Hello there" in out
    assert "<p>" in out


def test_multiline_matches_multiple_nodes():
    html = "<p>Line one</p><p>Line two</p>"
    old_plain = "Line one\nLine two"
    new_plain = "First\nSecond"
    out = merge_plain_into_html_if_unchanged(html, html, old_plain, new_plain)
    assert "First" in out and "Second" in out


def test_no_merge_when_plain_and_html_text_diverged():
    html = "<p>Only in HTML</p>"
    out = merge_plain_into_html_if_unchanged(
        html, html, "different plain than html", "new plain"
    )
    assert out == html


def test_empty_latest_uses_posted_html():
    """No prior version: HTML field content is stored as-is."""
    assert merge_plain_into_html_if_unchanged("", "<p>x</p>", "", "x") == "<p>x</p>"


def test_plain_text_from_html_strips_and_newlines():
    assert plain_text_from_html("<p>a</p><p>b</p>") == "a\nb"


def test_reconcile_html_wins_derives_plain():
    latest_h = "<p>Old</p>"
    latest_t = "Old"
    posted_h = "<p>New body</p>"
    posted_t = "stale plain"
    h, t = reconcile_template_bodies(latest_h, latest_t, posted_h, posted_t)
    assert "<p>New body</p>" in h
    assert t == "New body"


def test_reconcile_merge_plain_updates_html_and_text():
    latest_h = "<p>Line one</p><p>Line two</p>"
    latest_t = "Line one\nLine two"
    posted_h = latest_h
    posted_t = "First\nSecond"
    h, t = reconcile_template_bodies(latest_h, latest_t, posted_h, posted_t)
    assert "First" in h and "Second" in h
    assert "First" in t and "Second" in t


def test_reconcile_fallback_when_merge_fails():
    """Divergent stored pair + plain-only edit that cannot merge → minimal HTML."""
    latest_h = "<p>Only in HTML</p>"
    latest_t = "mismatch"
    posted_h = latest_h
    posted_t = "New plain only"
    h, t = reconcile_template_bodies(latest_h, latest_t, posted_h, posted_t)
    assert "<div>" in h and "<p>" in h
    assert "New plain only" in t


def test_reconcile_jinja_preserved_after_single_node_merge():
    latest_h = "<p>old</p>"
    latest_t = "old"
    posted_t = "Hi {{ name }}"
    h, t = reconcile_template_bodies(latest_h, latest_t, latest_h, posted_t)
    assert "{{ name }}" in h
    assert "{{ name }}" in t


def test_reconcile_jinja_preserved_in_fallback():
    """Merge cannot run (HTML/plain inconsistent); fallback wraps raw lines."""
    latest_h = "<p>Only in HTML</p>"
    plain = "Hello {% if x %}{{ y }}{% endif %}"
    h, t = reconcile_template_bodies(latest_h, "nope", latest_h, plain)
    assert "{%" in h and "{{" in h
    assert "{{ y }}" in t or "{{" in t
