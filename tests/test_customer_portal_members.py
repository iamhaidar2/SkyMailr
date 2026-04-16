"""Customer portal: members, invites, password reset, signup hardening."""

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.urls import reverse

from apps.accounts.models import (
    Account,
    AccountInvite,
    AccountInviteStatus,
    AccountMembership,
    AccountRole,
    AccountStatus,
)
from apps.accounts.services import invite_service
User = get_user_model()


@pytest.fixture
def owner_user(db):
    return User.objects.create_user("owner@example.com", password="SecurePass1!", email="owner@example.com")


@pytest.fixture
def owner_account(db, owner_user):
    acc = Account.objects.create(name="Mem Co", slug="mem-co", status=AccountStatus.ACTIVE)
    AccountMembership.objects.create(
        account=acc,
        user=owner_user,
        role=AccountRole.OWNER,
        is_active=True,
    )
    return acc


@pytest.fixture
def admin_user(db, owner_account):
    u = User.objects.create_user("admin@example.com", password="SecurePass1!", email="admin@example.com")
    AccountMembership.objects.create(
        account=owner_account,
        user=u,
        role=AccountRole.ADMIN,
        is_active=True,
    )
    return u


@pytest.fixture
def editor_user(db, owner_account):
    u = User.objects.create_user("editor@example.com", password="SecurePass1!", email="editor@example.com")
    AccountMembership.objects.create(
        account=owner_account,
        user=u,
        role=AccountRole.EDITOR,
        is_active=True,
    )
    return u


@pytest.mark.django_db
def test_members_list_visible_to_editor(client, editor_user, owner_account):
    client.force_login(editor_user)
    r = client.get(reverse("portal:members_list"))
    assert r.status_code == 200
    assert b"Members" in r.content or b"members" in r.content.lower()


@pytest.mark.django_db
def test_editor_cannot_invite(client, editor_user, owner_account):
    client.force_login(editor_user)
    r = client.get(reverse("portal:members_invite"))
    assert r.status_code == 403


@pytest.mark.django_db
def test_owner_can_create_invite(client, owner_user, owner_account):
    client.force_login(owner_user)
    r = client.post(
        reverse("portal:members_invite"),
        {"email": "new@example.com", "role": AccountRole.EDITOR},
    )
    assert r.status_code == 302
    assert AccountInvite.objects.filter(
        account=owner_account, email="new@example.com", status=AccountInviteStatus.PENDING
    ).exists()
    assert len(mail.outbox) == 1


@pytest.mark.django_db
def test_duplicate_pending_invite_blocked(client, owner_user, owner_account):
    client.force_login(owner_user)
    client.post(
        reverse("portal:members_invite"),
        {"email": "dup@example.com", "role": AccountRole.VIEWER},
    )
    r2 = client.post(
        reverse("portal:members_invite"),
        {"email": "dup@example.com", "role": AccountRole.VIEWER},
    )
    assert r2.status_code == 200
    assert AccountInvite.objects.filter(account=owner_account, email="dup@example.com").count() == 1


@pytest.mark.django_db
def test_cannot_invite_existing_member_email(client, owner_user, owner_account, admin_user):
    client.force_login(owner_user)
    r = client.post(
        reverse("portal:members_invite"),
        {"email": admin_user.email, "role": AccountRole.VIEWER},
    )
    assert r.status_code == 200
    assert b"already" in r.content.lower()


@pytest.mark.django_db
def test_invite_accept_creates_membership(client, owner_user, owner_account):
    inv, raw = invite_service.create_invite(
        account=owner_account,
        email="joiner@example.com",
        role=AccountRole.EDITOR,
        invited_by=owner_user,
    )
    joiner = User.objects.create_user("joiner@example.com", password="SecurePass1!", email="joiner@example.com")
    client.force_login(joiner)
    r = client.post(reverse("portal:invite_accept", kwargs={"token": raw}))
    assert r.status_code == 302
    assert AccountMembership.objects.filter(
        account=owner_account, user=joiner, role=AccountRole.EDITOR
    ).exists()
    inv.refresh_from_db()
    assert inv.status == AccountInviteStatus.ACCEPTED


@pytest.mark.django_db
def test_invite_cancel(client, owner_user, owner_account):
    inv, _ = invite_service.create_invite(
        account=owner_account,
        email="gone@example.com",
        role=AccountRole.VIEWER,
        invited_by=owner_user,
    )
    client.force_login(owner_user)
    r = client.post(reverse("portal:invite_cancel", kwargs={"invite_id": inv.id}))
    assert r.status_code == 302
    inv.refresh_from_db()
    assert inv.status == AccountInviteStatus.CANCELLED


@pytest.mark.django_db
def test_admin_cannot_edit_owner_membership(client, admin_user, owner_user, owner_account):
    om = AccountMembership.objects.get(account=owner_account, user=owner_user)
    client.force_login(admin_user)
    r = client.get(reverse("portal:member_edit", kwargs={"membership_id": om.id}))
    assert r.status_code == 403


@pytest.mark.django_db
def test_cannot_remove_last_owner(client, owner_user, owner_account):
    om = AccountMembership.objects.get(account=owner_account, user=owner_user)
    client.force_login(owner_user)
    r = client.post(
        reverse("portal:member_deactivate", kwargs={"membership_id": om.id}),
    )
    assert r.status_code == 302
    om.refresh_from_db()
    assert om.is_active is True


@pytest.mark.django_db
def test_password_reset_pages_load(client):
    r = client.get(reverse("portal:password_reset"))
    assert r.status_code == 200
    r2 = client.get(reverse("portal:password_reset_done"))
    assert r2.status_code == 200


@pytest.mark.django_db
def test_staff_operator_dashboard_still_works(staff_client):
    r = staff_client.get(reverse("ui:dashboard"))
    assert r.status_code == 200


@pytest.mark.django_db
def test_signup_honeypot_rejects(client):
    r = client.post(
        reverse("portal:signup"),
        {
            "company_website": "http://spam.com",
            "display_name": "Spammer",
            "email": "spam@example.com",
            "password1": "GoodPassphrase9!",
            "password2": "GoodPassphrase9!",
            "account_name": "Spam Inc",
            "account_slug": "spam-inc",
        },
    )
    assert r.status_code == 200
    assert not User.objects.filter(email="spam@example.com").exists()
