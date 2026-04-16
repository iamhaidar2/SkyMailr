# Account layer — phase 1 checklist

This file breaks the first implementation phase into concrete engineering tasks.

Reference architecture: `docs/13-multi-account-saas-plan.md`

## Phase 1 goal
Create the ownership layer above tenants without breaking existing tenant-key integrations.

---

## 1. Models

### Add `Account`
Suggested fields:
- `id`
- `name`
- `slug`
- `status`
- `billing_email`
- `plan_code`
- `metadata`
- `created_at`
- `updated_at`

### Add `AccountMembership`
Suggested fields:
- `id`
- `account`
- `user`
- `role`
- `is_active`
- `created_at`
- `updated_at`

### Update `Tenant`
Add:
- `account = ForeignKey(Account, related_name="tenants", ...)`

---

## 2. Migration strategy

### Migration A
- create `Account`
- create `AccountMembership`
- add nullable `Tenant.account`

### Migration B (data migration)
- create internal account:
  - name: `Haidar Internal`
  - slug: `haidar-internal`
- assign all existing tenants to that account
- optionally attach known internal Django users as owners/admins

### Migration C
- make `Tenant.account` non-nullable

---

## 3. Admin

Register in Django admin:
- `Account`
- `AccountMembership`

Update `TenantAdmin` to show:
- account
- slug
- status
- default sender email

---

## 4. Permission helpers

Add helper functions/decorators/services for:
- fetch accounts for current user
- check membership
- check role
- staff bypass

Suggested helpers:
- `get_user_accounts(user)`
- `user_has_account_access(user, account)`
- `user_has_account_role(user, account, roles)`

---

## 5. Tests

Add tests for:
- account creation model basics
- membership uniqueness/role behavior
- tenant must belong to an account after migration
- existing seeded/internal tenants are assigned to internal account
- staff retains access
- non-member cannot access account-scoped resources

---

## 6. Success criteria

Phase 1 is done when:
- database has `Account` and `AccountMembership`
- every `Tenant` belongs to an `Account`
- existing tenants migrate cleanly
- tests pass on Python 3.11
- no existing tenant-key send path breaks

---

## 7. Immediate follow-up after phase 1

Start phase 2:
- customer session auth path
- account membership checks in UI/views
- customer portal shell
