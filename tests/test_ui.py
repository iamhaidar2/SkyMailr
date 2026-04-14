import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

User = get_user_model()


@pytest.fixture
def staff_client(db, client):
    user = User.objects.create_user("ops", password="pass12345", is_staff=True)
    client.login(username="ops", password="pass12345")
    return client


def test_login_page_loads(client):
    r = client.get(reverse("ui:login"))
    assert r.status_code == 200


def test_root_redirects_unauthenticated(client):
    r = client.get(reverse("ui:dashboard"))
    assert r.status_code == 302
    assert "/login" in r["Location"]


def test_dashboard_requires_staff(client, db):
    User.objects.create_user("u", password="p", is_staff=False)
    client.login(username="u", password="p")
    r = client.get(reverse("ui:dashboard"))
    assert r.status_code == 403


def test_dashboard_ok(staff_client):
    r = staff_client.get(reverse("ui:dashboard"))
    assert r.status_code == 200


def test_messages_list_ok(staff_client):
    r = staff_client.get(reverse("ui:messages_list"))
    assert r.status_code == 200


def test_webhooks_list_ok(staff_client):
    r = staff_client.get(reverse("ui:webhooks_list"))
    assert r.status_code == 200


def test_setup_page_ok(staff_client):
    r = staff_client.get(reverse("ui:setup"))
    assert r.status_code == 200


def test_service_meta_public(client):
    r = client.get(reverse("ui:service_meta"))
    assert r.status_code == 200
    assert r.json()["service"] == "SkyMailr"


def test_api_health_unchanged(client):
    r = client.get("/api/v1/health/")
    assert r.status_code == 200
