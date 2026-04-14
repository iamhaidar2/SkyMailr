import pytest

from apps.providers.base import EmailMessageDTO
from apps.providers.dummy import DummyEmailProvider


@pytest.mark.django_db
def test_dummy_provider_stores():
    p = DummyEmailProvider()
    r = p.send_message(
        EmailMessageDTO(
            to_email="x@y.com",
            subject="S",
            html_body="<p>hi</p>",
            text_body="hi",
            from_email="a@b.com",
        )
    )
    assert r.success
    assert r.provider_message_id
