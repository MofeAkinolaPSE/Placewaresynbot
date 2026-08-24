# Task 002 – Logistics & Delivery Workflow Validation
# Development Task Request
## Project
Placeware ACE Platform – Logistics & Delivery Workflow

## Category
Quality Assurance / Validation

## Priority
High

---

# Objective

Validate, end-to-end and in a real browser, the full invoice-to-delivery workflow already implemented in the ACE Workstation — from a new client request through QC, Finance approval, dispatch, rider assignment via access code, live GPS tracking, and delivery confirmation — ahead of the upcoming live demo, and fix anything found broken along the way.

---

# Background

We are already live and preparing for a client-facing demo. The delivery pipeline has already been built: a client request is raised, it goes to QC to confirm the items are available, then to Finance for approval, and only then is it dispatched to a rider for delivery.

For rider tracking, the current (deliberate, phase-one) design is code-based: once a delivery is dispatched, a rider is assigned and given a short access code. The rider opens the tracking page in their phone's browser, enters the code, and the system starts live GPS tracking against that delivery automatically. There is no rider login/password in this phase — that is intentionally deferred. A future phase may move to full rider user accounts that auto-track on login, but that is out of scope here.

This task is **not** to build this feature — it already exists and has already passed backend/API-level checks. What has **not** yet been done is a real, human, browser-based walkthrough of the entire chain, on both desktop (staff side) and mobile (rider side). That is the gap this task closes before the demo.

---

# Existing Work

The following already exists in the repository and should not be redesigned unless a significant issue is found:

- Request creation (Frontdesk / Customer Workspace "Make New Request") which raises an invoice
- QC action panel — pass/fail an invoice, advances it to Finance
- Finance approval panel — approve/reject a QC-passed invoice
- Dispatch — approved invoices are sent to Logistics, creating a real delivery record
- Rider registration with a persistent, once-issued access code ("ACE Riders")
- Public rider sign-in page (`/rider`) — code entry, resolves the rider's currently assigned delivery and starts tracking automatically
- Live GPS tracking page (`/rider-track/:token`) — used by the rider's phone, and a live map for staff
- Manual rider-to-delivery assignment inside the Logistics Monitor
- An "Operations Queue" on the ACE Workstation dashboard showing in-flight deliveries
- Delivery confirmation (manual button, and automatic geofence detection on arrival), which also marks the originating invoice complete
- A full history/audit trail per invoice showing every stage it passed through

Your job is to walk through all of it as a real user would, on real devices, and fix whatever doesn't hold up.

---

# Primary Goals

## 1. End-to-End Workflow Validation

Starting from a brand-new client request, walk the entire chain through in the actual UI (not via API calls): request → QC → Finance → Dispatch → rider assignment → rider sign-in → live tracking → delivery confirmed → invoice shows completed. Confirm every step is reflected correctly for the next department to act on, without any manual database intervention.

## 2. Rider Access Code Flow

This is the part most likely to break in the real world, since it runs on a rider's own phone browser, not a desk. Register a rider, get their access code, and use it on an actual mobile device at `/rider`. Confirm it resolves the right delivery, starts tracking automatically, and that GPS updates keep flowing while the rider is moving (or simulated to move).

## 3. Multi-Role Testing

Test using separate accounts for QC, Finance, and Ops/Admin — not one admin account doing everything. A single-admin test hides role/permission bugs that a real multi-department demo will expose immediately.

## 4. Bug Triage & Fixes

Log everything found. Fix what's broken — this task is done when the workflow works, not when a bug list is produced.

---

# Engineering Expectations

Areas to pay particular attention to:

- Realtime behaviour — does the QC/Finance queue update live when another department acts, or does it require a manual refresh
- GPS tracking reliability on a real phone browser — intermittent signal, app backgrounded, battery saver mode
- Geofence auto-delivery-detection accuracy
- Error messaging when something fails (invalid code, expired session, no delivery assigned yet)
- Mobile browser compatibility specifically for `/rider` and `/rider-track/:token`, since these are the only two pages in the app a rider (not office staff) will ever touch
- What happens if a rider closes the browser mid-delivery and reopens it later

---

# Testing Requirements

Before this is considered demo-ready, confirm:

- A new request can be created and correctly lands in the QC queue
- QC pass and QC fail both behave correctly
- Finance approve and reject both behave correctly
- Dispatch creates a real delivery and it appears in Logistics/Operations Queue
- A rider can be assigned to a delivery manually, and the delivery status updates
- A rider's access code correctly resolves their assigned delivery and starts tracking
- Live position updates are visible to staff while the rider is "moving"
- Delivery can be confirmed both manually and via geofence auto-detection
- The originating invoice correctly reflects status at every stage, ending in "completed"
- No duplicate or lost updates when multiple people act on the same request around the same time
- Graceful behaviour if the rider loses signal or the app is closed mid-delivery

---

# Deliverables

## Functional Deliverables

- A validated, demo-ready delivery workflow
- Any bugs found during testing are fixed, not just documented

## Technical Deliverables

- Notes on any code changes made during fixes
- Any newly discovered configuration or environment requirements

## Validation Deliverables

Demonstration showing, live in a browser (not via API calls):

- A new request created and moved through QC and Finance
- Dispatch to a rider
- The rider signing in with their code on a phone
- Live tracking visible to staff
- Delivery confirmed
- The invoice showing as completed

---

# Definition of Done

This task is complete when:

- The full chain works start to finish in a real browser session, for each role involved.
- The rider access-code sign-in and live tracking work reliably on an actual phone.
- No manual database or API workarounds are needed anywhere in the flow.
- The workflow is ready to demo live to the client.
