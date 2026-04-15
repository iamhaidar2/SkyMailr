# Templates and workflows

## Template lifecycle

```text
Create template → (optional) LLM generate/revise draft versions → preview with JSON context
    → approve latest version → sends use approved content only
```

| Stage | Where | Notes |
|-------|--------|------|
| **Draft versions** | LLM generate/revise, manual edits | Not used for production send until approved |
| **Preview** | API `POST .../preview/`, operator UI | Validates variables, renders latest version (may differ from approved) |
| **Approve** | API `.../approve/`, operator UI | Marks latest version approved; unsets other `is_current_approved` |
| **Send** | API send-template, UI send, workflow step | Uses **`current_approved_version`** only |

### What “approved” means

- One version per template is **`is_current_approved=True`**.
- **`create_templated_message`** loads that version for render. If **none**, send fails with a clear error.
- **Transactional reliability:** you don’t want draft copy going to users — hence approval gate.

### Required variables

- `TemplateVariable` rows define **`name`**, **`is_required`**, description.
- **`TemplateValidationService.validate_context`** runs before render on sends and previews.
- Missing required keys → render failure → message may be **`failed`** with `last_error` set.

## LLM: allowed vs forbidden

| Allowed | Forbidden |
|---------|-----------|
| Generate/revise **template body** (subject/HTML/text) as new versions | Choosing recipients, suppressions, or sending mail |
| Structured JSON briefs → draft content | Bypassing approval for production sends |

Email delivery is **always** deterministic code: pipeline, Celery, provider.

## Workflow concepts

| Concept | Meaning |
|---------|---------|
| **Workflow** | Named sequence container per tenant (`slug`, `name`) |
| **Step** | Ordered row: e.g. `SEND_TEMPLATE`, `WAIT_DURATION`, `END` |
| **Enrollment** | A recipient + metadata (e.g. `template_context`) entered into a workflow |
| **Execution** | Runtime state: current step, `next_run_at`, status |

### Enrollment

- **API:** `POST /api/v1/workflows/<workflow_id>/enroll/` with `recipient_email`, optional `metadata`.
- **Metadata:** Often `{"template_context": {"user_name": "..."}}` for send steps — must satisfy template variables.

### Execution

- **Celery beat** runs `process_workflow_due_steps` → `process_due_executions`.
- Due executions move steps forward; **SEND_TEMPLATE** calls the same **`create_templated_message`** as the API.

### Common failure points

| Symptom | Check |
|---------|--------|
| Step “template missing” | Step `template` FK or `template_key` + tenant match |
| Send **failed** | Render/validation — see message `last_error` |
| Nothing sends | Worker/beat down; or template not **approved** |
| Wrong content | Approved version vs preview confusion — sends use **approved** only |

## Preview vs production send

- **Preview** renders the **latest** version (API docstring / UI copy warn of this).
- **Send** uses **approved** version only.

Always approve before trusting production traffic.

## Related

- Debugging workflows: [09-debugging-and-runbook.md](09-debugging-and-runbook.md)
- Architecture flows: [01-architecture.md](01-architecture.md)
