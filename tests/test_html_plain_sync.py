"""Tests for merging plain-text edits into unchanged HTML."""

from apps.email_templates.services.html_plain_sync import merge_plain_into_html_if_unchanged


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
