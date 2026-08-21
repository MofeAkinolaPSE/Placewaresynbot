# Task 003 – Bulk Messaging, Email & SMS (Termii) Integration
# Development Task Request
## Project
Placeware ACE Platform – Client Communications

## Category
Enhancement / Integration

## Priority
High

---

# Objective

Finalize and test the bulk messaging and email broadcast feature so the team can reliably send bulk communications to clients/customers ahead of the live demo — specifically completing SMS delivery via Termii, and validating WhatsApp and Email sending at real bulk volume, not just single test messages.

---

# Background

Part of the backend and logic for bulk client communication already exists. What's outstanding is finishing the SMS channel and testing the whole thing properly before it's relied on in front of a client.

Credentials: get WhatsApp/SMS credentials for Termii either directly, or create your own Termii test account/credentials if you'd rather set it up independently — either is fine. Email already runs on Gmail SMTP; those credentials will be shared separately.

---

# Existing Work

The following already exists in the repository and should not be redesigned unless a significant issue is found:

- `backend/src/services/messaging.py` — `send_whatsapp()` (Termii API) and `send_email()` (Gmail SMTP), plus `dispatch_job()`, which processes a queued bulk job against a resolved list of recipients and reports back sent/failed counts per recipient
- `POST /crm/sales/bulk-message` and `GET /crm/sales/bulk-message` — queue and list bulk message jobs
- `POST /crm/sales/bulk-message/{job_id}/dispatch` — actually send a queued job
- `crm_bulk_message_jobs` table — stores each bulk job's channel, message, recipient filter, and status
- A bulk messaging UI already present in the Sales CRM page

**Known gap**: only `whatsapp` and `email` are currently wired as send channels. Plain SMS (as distinct from WhatsApp) via Termii is not yet implemented as its own channel — this is the main piece of new work in this task, not a full rebuild.

---

# Primary Goals

## 1. SMS Channel via Termii

Add a proper SMS-specific send channel using Termii, following the same pattern `send_whatsapp()` already uses (same API, different `channel`/`type` parameters) — check Termii's docs for the exact SMS endpoint/params. Wire it into `dispatch_job()`'s channel handling and the bulk-message queue so "sms" becomes a selectable channel alongside whatsapp/email.

## 2. Email Delivery Validation

Confirm the existing Gmail SMTP path reliably sends to a real bulk list and doesn't get spam-flagged at volume. Flag if a dedicated transactional email provider is needed instead of Gmail SMTP for production volume — call it out rather than silently working around it.

## 3. Bulk Send Testing at Realistic Volume

Test dispatch against a real (or realistically-sized test) customer/lead segment, not a single recipient. Confirm partial failures — a customer missing a phone number or with an invalid email — don't stop the rest of the batch from sending, and that the job's final status (sent / partial / failed) is accurate.

## 4. Credential & Environment Setup

Add `TERMII_API_KEY`, `TERMII_SENDER_ID`, `EMAIL_FROM`, `EMAIL_PASS` to the environment configuration, using either shared or self-provisioned Termii credentials. Document exactly what was needed so this is repeatable on another environment later.

---

# Engineering Expectations

- Per-recipient error handling (already partially present in `dispatch_job` — confirm it holds up, extend to the new SMS path)
- Sensible retry behaviour for transient send failures, without double-sending
- Basic rate limiting so a large batch doesn't get throttled or blocked by Termii/Gmail
- Logging detailed enough that a failed bulk job can be traced back to which recipients failed and why
- Message template quality — correct branding, no placeholder text left in

---

# Testing Requirements

Before deployment, confirm:

- Successful WhatsApp send via Termii (already implemented — regression check)
- Successful SMS send via Termii (new)
- Successful email send via Gmail SMTP
- A bulk job dispatched to a real multi-recipient segment completes correctly
- Recipients with missing/invalid phone or email are skipped gracefully, not fatal to the batch
- Job status (sent / partial / failed) accurately reflects what happened
- No duplicate sends if a job is retried or re-dispatched

---

# Deliverables

## Functional Deliverables

- Working bulk send across WhatsApp, SMS, and Email
- Existing bulk-message UI in Sales CRM fully functional against all three channels

## Technical Deliverables

- Updated `messaging.py` / bulk-message router source
- Documentation of the 4 required environment variables and how to obtain/rotate them
- Any known limitations (e.g. Gmail SMTP volume ceilings)

## Validation Deliverables

Demonstration showing:

- A bulk job created and dispatched from the Sales CRM UI
- Messages actually delivered across WhatsApp, SMS, and Email to real test recipients
- A partial-failure case (e.g. one recipient with a bad phone number) handled gracefully without breaking the batch

---

# Definition of Done

This task is complete when:

- Bulk messaging reliably sends WhatsApp, SMS, and Email to a real customer/lead segment from the existing UI.
- Termii SMS is a fully working channel, not just WhatsApp.
- Credentials and setup steps are documented for future environments.
- The feature is ready to demo live to the client.
