Morning, M. ☕

Let's do it.

Yesterday, we completed **Phase 1 — Architecture**.

Today, we begin **Phase 2 — Engineering Translation**, which I think will become the most valuable set of documents in the project.

One thing I want to change before we start.

Yesterday we were writing for:

> Architects
> Product Owners
> Hospital Management

Today, we're writing for:

* Backend Engineers
* Frontend Engineers
* Database Engineers
* QA Engineers
* AI Engineers
* DevOps
* Technical Leads

These documents should be detailed enough that an engineering team can build SynBot Health with minimal interpretation.

I also think we should introduce a new naming convention to distinguish them from the SHAS architecture standards.

Instead of continuing SHAS, I'd create a dedicated engineering specification series.

# SynBot Health Engineering Specification (SHES)

Example:

* SHES-001 — Universal Department Workspace Engineering Specification
* SHES-002 — Universal Workflow Engine Engineering Specification
* SHES-003 — Clinical Workspace Engineering Specification

This keeps the architecture (SHAS) separate from implementation (SHES), which is common practice in enterprise architecture.

---

# SynBot Health Engineering Specification 001

# Universal Department Workspace Engineering Specification (UDWES)

**Version:** 1.0
**Project:** SynBot Health
**Engineering Specification:** SHES-001
**Architecture Reference:** SHAS-001 – Universal Department Workspace Standard
**Status:** Engineering Specification

---

# 1. Purpose

This specification translates **SHAS-001** into an implementable engineering blueprint.

It defines:

* Backend services
* Frontend architecture
* Database entities
* API contracts
* Event interactions
* State management
* UI component requirements
* Acceptance criteria

The goal is to ensure every department workspace is implemented consistently across the platform.

---

# 2. Scope

This specification applies to every departmental workspace including:

* OPD
* IPD
* Emergency
* Laboratory
* Radiology
* Pharmacy
* Billing
* HMO
* Theatre
* Dialysis

Future departments inherit this specification.

---

# 3. Engineering Objectives

Every department workspace shall:

* Load quickly
* Support real-time updates
* Minimize page navigation
* Provide contextual patient information
* Execute workflow actions
* Remain component-driven
* Support responsive layouts

---

# 4. Architecture Mapping

| SHAS     | SHES Responsibility              |
| -------- | -------------------------------- |
| SHAS-001 | Defines workspace philosophy     |
| SHES-001 | Defines workspace implementation |

---

# 5. Backend Services

The workspace consumes multiple backend services.

```text
Department Workspace

↓

Authentication Service

↓

Patient Service

↓

Encounter Service

↓

Workflow Service

↓

Queue Service

↓

Notification Service

↓

Audit Service
```

No workspace communicates directly with the database.

Everything passes through service APIs.

---

# 6. Backend Modules

Every department implements:

```text
/workspaces

↓

Department Workspace Controller

↓

Department Workspace Service

↓

Department Repository

↓

Workflow Client

↓

Queue Client

↓

Audit Client
```

Each module owns only presentation-oriented orchestration.

Business logic remains inside domain services.

---

# 7. Frontend Architecture

Recommended React structure:

```text
src/

modules/

department/

components/

pages/

hooks/

services/

types/

store/
```

Every department follows the same structure.

---

# 8. Workspace Layout

Every workspace consists of independent panels.

```text
+------------------------------------------------------------+
| Header                                                     |
+------------------------------------------------------------+
| Queue | Patient Context | Main Workspace | Action Sidebar  |
+------------------------------------------------------------+
| Status Bar                                                 |
+------------------------------------------------------------+
```

Each panel is independently refreshable.

---

# 9. Core Components

Reusable components include:

## QueuePanel

Responsibilities:

* Display queue
* Search
* Filter
* Sort
* Real-time updates

---

## PatientContextPanel

Displays:

* Demographics
* Alerts
* Allergies
* Active Encounter
* Recent History

---

## WorkspacePanel

Displays department-specific forms.

Examples:

* Consultation
* Laboratory
* Radiology
* Pharmacy

---

## ActionPanel

Displays workflow buttons.

Examples:

* Call Patient
* Start Consultation
* Complete Procedure

---

## StatusBar

Displays:

* Connection status
* Current user
* Department
* Active encounter
* Notifications

---

# 10. State Management

Recommended state slices:

```text
workspace

queue

patient

encounter

workflow

notifications

loading

errors
```

State should be normalized.

No duplicated patient objects.

---

# 11. API Endpoints

Example workspace endpoints:

```http
GET /workspace/{department}

GET /workspace/{department}/queue

GET /workspace/patient/{id}

POST /workspace/action

GET /workspace/notifications

GET /workspace/context/{encounterId}
```

Workspace endpoints aggregate information.

They do not replace domain services.

---

# 12. Events Consumed

Workspace subscribes to:

* Queue Updated
* Patient Assigned
* Workflow Changed
* New Notification
* Encounter Updated
* Patient Checked In
* Patient Checked Out

Events refresh only affected components.

Not the whole page.

---

# 13. Events Published

Workspace actions generate events.

Examples:

Call Patient

↓

Patient Called Event

---

Complete Consultation

↓

Consultation Completed Event

---

Medication Dispensed

↓

Medication Dispensed Event

---

These events trigger downstream automation.

---

# 14. Loading Strategy

Components load independently.

Example

```text
Queue

↓

Immediate

Patient Context

↓

After Patient Selected

Workspace

↓

After Encounter Loaded

Sidebar

↓

Background
```

This reduces perceived latency.

---

# 15. Error Handling

Each component handles errors independently.

Queue failure

↓

Queue Error Component

Patient Context

↓

Context Error Component

Workspace

↓

Retry

No single component should crash the entire workspace.

---

# 16. Security

Workspace enforces:

* Authentication
* Role validation
* Department validation
* Encounter validation
* Patient authorization

Unauthorized actions should never reach business services.

---

# 17. Performance Requirements

Target metrics:

Initial load

<2 seconds

Queue refresh

<1 second

Patient switch

<500 ms

Action response

<1 second

Background refresh

Non-blocking

These targets may be refined during performance testing but provide engineering goals from the outset.

---

# 18. Logging

Workspace logs:

* User actions
* API failures
* Rendering errors
* Performance metrics
* Navigation events

Operational logs complement the audit model defined in SHAS-014.

---

# 19. Testing Requirements

Unit Tests

* Component rendering
* Hooks
* State updates

Integration Tests

* Queue interactions
* Patient selection
* API communication

End-to-End Tests

* Login
* Queue workflow
* Patient interaction
* Department actions

Regression Tests

* Shared component behavior
* Layout consistency
* Cross-browser compatibility

---

# 20. Acceptance Criteria

The implementation is complete when:

* Every department uses the same workspace framework.
* Queue updates occur in real time.
* Patient context updates without page reloads.
* Workflow actions are immediately reflected in the UI.
* Shared components are reused across departments.
* Backend services remain decoupled from UI concerns.
* The workspace meets performance and security objectives.

---

# 21. Implementation Roadmap

### Phase A — Foundation

* Shared layout framework
* Authentication integration
* Navigation shell

### Phase B — Shared Components

* QueuePanel
* PatientContextPanel
* ActionPanel
* StatusBar

### Phase C — Service Integration

* Queue API
* Workflow API
* Notification API
* Patient Context API

### Phase D — Department Specialization

* OPD workspace
* IPD workspace
* Emergency workspace
* Laboratory workspace
* Remaining departments

---

# 22. Developer Deliverables

The engineering team shall produce:

### Backend

* Workspace aggregation service
* API controllers
* Event subscribers
* Authorization middleware

### Frontend

* Shared workspace layout
* Reusable components
* State management
* API client layer

### QA

* Test plans
* Automated test suites
* Performance validation
* Accessibility testing

### DevOps

* Deployment configuration
* Monitoring dashboards
* Health checks
* CI/CD integration

---

# Architect's Note

This document establishes a pattern that every subsequent engineering specification will follow:

* **SHAS** answers **"What should the platform do?"**
* **SHES** answers **"Exactly how do engineers build it?"**

By separating architecture from implementation, we gain two advantages:

1. **Stability** — The architecture can remain largely unchanged even if the technology stack evolves.
2. **Execution** — Engineering teams receive concrete implementation guidance without having to reinterpret architectural intent.

I also want to propose one refinement before we continue with SHES-002 onward.

Rather than treating these purely as specification documents, we can make each SHES document **developer-ready** by including:

* File and folder structure
* Database tables and relationships
* FastAPI endpoint definitions
* Pydantic request/response models
* React component hierarchy
* Zustand/Redux state slices
* Event payload schemas
* Sequence diagrams
* QA test cases
* Acceptance tests

That would make each SHES document effectively a **complete engineering playbook**, allowing the backend and frontend agents to implement features with almost no ambiguity. Given the quality of the architecture we've already built, I think this is the right level of detail for Phase 2.
Perfect. This is exactly where I wanted us to go.

The first SHES document established **the physical workspace** (the screen).

Now we build **the brain of SynBot Health**.

If SHES-001 defines **where users work**, then **SHES-002 defines how the hospital thinks**.

Yesterday we agreed on something that I think is one of SynBot Health's biggest differentiators:

> **Nobody manually moves patients anymore.**

The workflow engine does.

Doctors simply finish consultations.

Nurses simply finish vitals.

Laboratory simply authenticates results.

The Workflow Engine decides what happens next.

That becomes the heart of the platform.

---

# SynBot Health Engineering Specification 002

# Universal Workflow Engine Engineering Specification (UWES)

**Version:** 1.0
**Project:** SynBot Health
**Engineering Specification:** SHES-002
**Architecture Reference:** SHAS-002 – Universal Workflow Engine Standard
**Status:** Engineering Specification

---

# 1. Purpose

This specification translates SHAS-002 into an engineering implementation.

It defines the event-driven workflow engine responsible for orchestrating every patient movement, departmental transition, task assignment, queue update, and workflow automation throughout SynBot Health.

The Workflow Engine is the central orchestration layer of the platform.

It does **not** perform clinical work.

It coordinates it.

---

# 2. Design Philosophy

Traditional HMS:

```text
User

↓

Clicks

↓

Moves Patient

↓

Updates Status

↓

Notifies Next Department
```

SynBot Health:

```text
User

↓

Completes Work

↓

Workflow Engine

↓

Updates Status

↓

Moves Queue

↓

Assigns Next Department

↓

Creates Tasks

↓

Publishes Events

↓

Sends Notifications
```

The user performs healthcare.

The platform performs coordination.

---

# 3. Responsibilities

The Workflow Engine owns:

* Workflow orchestration
* State transitions
* Queue movement
* Department routing
* Task creation
* Notification triggers
* Event publication
* SLA monitoring
* Automation rules

It does **not** own:

* Clinical documentation
* Billing calculations
* Laboratory testing
* Radiology reporting
* Authentication
* Authorization

---

# 4. Engineering Architecture

```text
Client Action

↓

Workflow API

↓

Workflow Engine

↓

Rule Engine

↓

State Machine

↓

Event Publisher

↓

Queue Engine

↓

Notification Engine

↓

Audit Engine
```

The Workflow Engine becomes the orchestration layer between all domain services.

---

# 5. Core Backend Modules

```text
/workflow

controller.py

service.py

rule_engine.py

state_machine.py

transition_validator.py

queue_manager.py

task_manager.py

event_publisher.py

notification_dispatcher.py

audit_logger.py
```

Each module owns one responsibility.

---

# 6. Domain Model

Core entities:

Workflow

↓

Workflow Instance

↓

Workflow State

↓

Transition

↓

Action

↓

Event

↓

Task

↓

Queue Assignment

↓

Audit Record

---

# 7. Database Tables

Core tables:

```text
workflow_definition

workflow_state

workflow_transition

workflow_instance

workflow_action

workflow_event

workflow_task

workflow_queue

workflow_history
```

All transitions should be persisted.

No workflow state should exist only in memory.

---

# 8. Workflow State Machine

Every workflow follows:

```text
Current State

↓

Validate

↓

Execute Rules

↓

Approve Transition

↓

Generate Events

↓

Update Queue

↓

Create Tasks

↓

Notify Users

↓

Persist History
```

Every transition is deterministic.

---

# 9. Standard Workflow States

Example patient states:

Registered

↓

Waiting Vitals

↓

Vitals Complete

↓

Waiting Doctor

↓

Consultation

↓

Investigations

↓

Treatment

↓

Billing

↓

Discharge

Departments may extend states.

They should never redefine existing core states.

---

# 10. Workflow Rules Engine

Business rules remain configurable.

Example:

```text
IF

Vitals Complete

AND

Consultation Required

THEN

Move Patient

↓

Doctor Queue

↓

Publish Event

↓

Notify Doctor
```

Rules should be declarative rather than hard-coded where possible.

---

# 11. Transition Validation

Before any transition:

Validate:

* Active Encounter
* Required Documentation
* User Permissions
* Department Ownership
* Required Clinical Actions
* Required Financial Conditions

Invalid transitions are rejected with explicit reasons.

---

# 12. API Endpoints

```http
POST /workflow/start

POST /workflow/action

GET /workflow/{id}

GET /workflow/history/{encounterId}

GET /workflow/tasks

GET /workflow/queue

POST /workflow/retry
```

Workflow endpoints orchestrate behavior but defer business logic to domain services.

---

# 13. Event Model

Example events:

```text
VitalsCompleted

ConsultationStarted

ConsultationCompleted

LabRequested

LabCompleted

PrescriptionCreated

MedicationDispensed

PatientAdmitted

PatientDischarged

ClaimSubmitted
```

Every major workflow action publishes an event.

---

# 14. Event Payload

Standard payload:

```json
{
  "eventId": "",
  "eventType": "",
  "patientId": "",
  "encounterId": "",
  "department": "",
  "performedBy": "",
  "timestamp": "",
  "metadata": {}
}
```

Payloads should be versioned to support future evolution.

---

# 15. Queue Engine

Responsibilities:

* Assign queues
* Remove completed work
* Re-prioritize
* Escalate delays
* Support emergency overrides

Queue movement must be automatic.

---

# 16. Task Engine

Automatically generates tasks.

Examples:

Doctor finishes consultation.

↓

Task Created

↓

Laboratory

---

Laboratory authenticates result.

↓

Task Created

↓

Doctor Review

---

Doctor prescribes medication.

↓

Task Created

↓

Pharmacy

Users never manually assign downstream work.

---

# 17. Notification Integration

Workflow events trigger notifications.

Example:

```text
Workflow Event

↓

Notification Engine

↓

Role Resolution

↓

Delivery Channel

↓

Acknowledgement

↓

Audit
```

Notification content is determined by SHAS-008 policies.

---

# 18. Workflow Recovery

If failures occur:

* Retry transient failures
* Prevent duplicate transitions
* Maintain idempotency
* Preserve audit history
* Allow administrator replay where appropriate

Recovery should never create inconsistent patient states.

---

# 19. Audit Integration

Every transition records:

* Previous State
* New State
* User
* Department
* Timestamp
* Trigger
* Event Generated
* Validation Outcome

Workflow history becomes immutable after persistence.

---

# 20. Frontend Responsibilities

Frontend never decides workflow.

Frontend simply sends:

```text
Action

↓

Workflow API

↓

Receives Updated State

↓

Refresh Components
```

Business transitions remain backend-controlled.

---

# 21. Performance Targets

Workflow validation:

<100 ms

Transition execution:

<300 ms

Queue update:

<500 ms

Notification creation:

<1 second

End-to-end transition:

<2 seconds

These targets should be validated under production-scale load.

---

# 22. Testing Strategy

Unit Tests

* Rule evaluation
* Transition validation
* State machine logic

Integration Tests

* Queue movement
* Event publication
* Notification generation

Load Tests

* 1,000 concurrent transitions
* High-volume queue updates
* Burst event processing

Chaos Tests

* Service interruption
* Duplicate requests
* Message replay
* Partial failures

---

# 23. Acceptance Criteria

The Workflow Engine implementation is complete when:

* Users perform only clinical or operational actions.
* All patient movement is orchestrated automatically.
* Workflow transitions are validated consistently.
* Queue updates occur without manual intervention.
* Events are published reliably.
* Tasks are generated automatically.
* Notifications are triggered appropriately.
* Every transition is fully auditable.
* Recovery mechanisms prevent duplicate or inconsistent workflow execution.

---

# 24. Backend Deliverables

* Workflow orchestration service
* State machine framework
* Rule evaluation engine
* Queue manager
* Task manager
* Event publisher
* Transition validator
* Audit integration

---

# 25. Frontend Deliverables

* Workflow action components
* Transition confirmation dialogs
* Queue refresh hooks
* Task indicators
* Workflow history viewer
* Real-time status updates

---

# 26. QA Deliverables

* Workflow transition test suite
* State validation tests
* Event verification
* Queue integrity testing
* Regression testing
* Performance benchmarking

---

# 27. DevOps Deliverables

* Event broker configuration (e.g., RabbitMQ, Kafka, or equivalent)
* Dead-letter queue monitoring
* Workflow metrics dashboard
* Distributed tracing
* Health checks
* Horizontal scaling configuration

---

# Architect's Note

This document defines the **operating system of SynBot Health**.

Every department—OPD, IPD, Emergency, Laboratory, Radiology, Pharmacy, Billing, HMO, Theatre, and Dialysis—executes its own work, but none of them manage patient progression directly.

The Workflow Engine becomes the **single source of truth** for movement, orchestration, and coordination.

That decision gives us several long-term advantages:

* **Consistency:** Every department follows the same orchestration model.
* **Extensibility:** New departments inherit workflow behavior without custom logic.
* **Auditability:** Every transition is recorded and reproducible.
* **Automation:** Manual queue management is eliminated.
* **AI Readiness:** The Workflow Engine provides a rich event stream that the SHAS-015 Clinical Intelligence layer can consume for prediction, optimization, and decision support.

## Engineering Progress

### SHES Engineering Specifications

* ✅ **SHES-001** – Universal Department Workspace Engineering Specification
* ✅ **SHES-002** – Universal Workflow Engine Engineering Specification

We now have the **user interface shell** (SHES-001) and the **orchestration engine** (SHES-002). Together, they form the foundation on which every other engineering specification will be built.

The next logical document is **SHES-003 – Clinical Workspace Engineering Specification**, where we'll define the implementation of the clinician's primary workspace, including the CPRS-inspired encounter view, longitudinal patient context, note-taking, order entry, and embedded workflow actions. That workspace is where the philosophy we discussed with Royan—*"stay on one screen, complete your work, let the system coordinate everything else"*—becomes a concrete engineering design.
Excellent.

This is probably the most important engineering document we'll write.

If **SHES-002** is the brain of SynBot Health...

then **SHES-003** is the face of SynBot Health.

This is the screen clinicians will spend **80–90% of their day** using.

And I want to make one architectural decision before we start because it aligns perfectly with everything we learned from Royan.

---

# One Workspace. One Patient. Zero Navigation.

Yesterday we repeatedly came back to the same philosophy from the meetings:

> **"I don't want to go to another page."**

That single sentence should become an engineering principle.

Traditional HMS:

```
Queue

↓

Open Patient

↓

History

↓

Close

↓

Open Notes

↓

Close

↓

Open Labs

↓

Close

↓

Open Prescription

↓

Close

↓

Billing

↓

Close
```

SynBot Health

```
Queue

↓

Patient Selected

↓

Everything appears

↓

Complete work

↓

Workflow Engine

↓

Next Patient
```

That changes everything.

We're no longer building pages.

We're building a **Clinical Workspace**.

Think of it like VS Code.

Think of it like Figma.

Think of it like Salesforce Lightning.

Everything exists inside a single workspace.

---

# SynBot Health Engineering Specification 003

# Clinical Workspace Engineering Specification (CWES)

**Version:** 1.0

**Project:** SynBot Health

**Engineering Specification:** SHES-003

**Architecture Reference:**

* SHAS-003 – Universal Clinical Workspace
* SHAS-001 – Universal Department Workspace
* SHAS-002 – Workflow Standard

**Status:** Engineering Specification

---

# 1. Purpose

The Clinical Workspace is the primary engineering implementation of the SynBot Health user experience.

It provides clinicians with a unified patient-centered interface that enables them to perform every clinical activity from a single workspace while the Workflow Engine manages coordination behind the scenes.

The workspace shall minimize navigation, reduce cognitive load, and maximize workflow efficiency.

---

# 2. Engineering Philosophy

The Clinical Workspace is built around one principle:

> **Bring the information to the clinician—not the clinician to the information.**

Users should not search for information that the platform already knows is relevant.

---

# 3. Core Design Principles

The workspace shall be:

* Patient-centric
* Context-aware
* Event-driven
* Component-based
* Real-time
* Keyboard friendly
* Mobile responsive (tablet compatible)
* Low-click

Every design decision should reduce interaction cost.

---

# 4. Engineering Architecture

```text
Queue Selection

↓

Workspace Shell

↓

Patient Context Engine

↓

Clinical Workspace

↓

Workflow Engine

↓

Event Bus

↓

Audit Engine
```

The workspace is an orchestration layer.

Clinical logic remains inside backend services.

---

# 5. Frontend Module Structure

```
src/

modules/

clinical-workspace/

components/

panels/

hooks/

services/

types/

store/

utils/
```

The workspace is its own independent application module.

---

# 6. Workspace Layout

```
+--------------------------------------------------------------+
| Header                                                       |
+--------------------------------------------------------------+
| Queue | Patient Summary | Clinical Workspace | Quick Actions |
+--------------------------------------------------------------+
| Bottom Drawer / Timeline / Notifications                     |
+--------------------------------------------------------------+
```

Everything should be visible without leaving the workspace.

---

# 7. Workspace Components

## Queue Panel

Purpose

Displays every patient currently assigned to the logged-in clinician or department.

Functions

* Search
* Filters
* Priority indicators
* Waiting time
* Current workflow state
* Queue refresh
* Drag disabled (workflow controlled)

---

## Patient Summary Panel

Displays:

* Name
* Age
* Gender
* MRN
* Allergies
* Alerts
* Active Encounter
* Current Diagnosis
* Current Medications
* Current Location
* HMO Status

This panel updates automatically when another patient is selected.

---

## Clinical Workspace Panel

This becomes the primary working surface.

Contains:

* CPRS Notes
* SOAP Notes
* Diagnosis
* Orders
* Medication
* Procedures
* Follow-up
* Clinical Timeline

Only one patient exists inside this workspace at a time.

---

## Quick Actions Panel

Examples

Call Patient

Start Consultation

Record Vitals

Order Labs

Order Imaging

Prescribe Medication

Request Admission

Discharge

End Consultation

Actions adapt dynamically according to the current workflow state.

---

## Timeline Drawer

Displays:

* Encounter History
* Orders
* Medications
* Laboratory Events
* Radiology Events
* Admissions
* Procedures
* Billing Events

Chronological.

Always.

---

# 8. CPRS Workspace

This is one area I think we should improve beyond Hope.

Instead of static notes:

```
Encounter

↓

SOAP

↓

Diagnosis

↓

Orders

↓

Prescription

↓

Disposition
```

The workspace becomes:

```
Conversation

↓

Clinical Note

↓

Diagnosis

↓

Orders

↓

Workflow

↓

AI Summary

↓

Audit
```

Everything is connected.

---

# 9. Smart Note Editor

The editor supports:

* Rich text
* Structured templates
* Voice dictation
* Auto-save
* Clinical snippets
* Expandable sections
* AI assistance
* Medical abbreviations
* Version history

Saving should occur continuously.

Never require explicit save.

---

# 10. Context Engine

The workspace loads:

Patient

↓

Encounter

↓

Previous Encounters

↓

Allergies

↓

Medications

↓

Labs

↓

Imaging

↓

Diagnoses

↓

Vitals

↓

Care Plans

↓

Outstanding Tasks

↓

Alerts

Everything loads automatically.

---

# 11. Tabs

Instead of pages:

The workspace contains tabs.

Examples

Overview

Clinical Notes

Orders

Laboratory

Radiology

Medication

Timeline

Documents

Billing Summary

AI Assistant

Tabs never unload patient context.

---

# 12. API Endpoints

```
GET /clinical/workspace/{encounterId}

GET /clinical/context/{patientId}

POST /clinical/note

POST /clinical/order

POST /clinical/prescription

GET /clinical/timeline

GET /clinical/tasks

POST /clinical/action
```

These APIs aggregate information from multiple backend services.

---

# 13. State Management

Suggested Zustand slices:

```
workspaceStore

patientStore

encounterStore

noteStore

workflowStore

orderStore

timelineStore

notificationStore
```

Each slice owns a single responsibility.

---

# 14. Component Communication

Components never communicate directly.

Everything flows through shared state.

```
Queue

↓

Store

↓

Patient Context

↓

Clinical Notes

↓

Orders

↓

Timeline

↓

Actions
```

Loose coupling improves maintainability.

---

# 15. Real-Time Updates

Subscribe to:

* Encounter Updated
* Lab Result Available
* Imaging Report Ready
* Medication Dispensed
* Workflow Changed
* Billing Updated
* Critical Alert

Only affected components should refresh.

---

# 16. AI Integration

The AI Panel becomes another workspace component.

Capabilities include:

Patient Summary

↓

Encounter Summary

↓

Suggested ICD

↓

Suggested Orders

↓

Documentation Assistance

↓

Medication Safety

↓

Follow-up Suggestions

↓

Clinical Timeline Summary

AI never modifies clinical records automatically.

---

# 17. Keyboard Shortcuts

Examples

Ctrl+K

Search Patient

---

Ctrl+N

New Note

---

Ctrl+L

Order Lab

---

Ctrl+R

Order Radiology

---

Ctrl+P

Prescription

---

Ctrl+S

Manual Save (optional)

Power users should complete workflows without relying solely on the mouse.

---

# 18. Performance Targets

Workspace load

<2 seconds

Patient switch

<300 ms

Context loading

<500 ms

Note auto-save

<250 ms

Real-time updates

<1 second

---

# 19. Error Strategy

Patient context failure

↓

Retry Context Only

---

Timeline failure

↓

Retry Timeline

---

Lab failure

↓

Retry Lab Component

Failures remain isolated.

---

# 20. Testing

Unit

* Components
* Hooks
* Stores

Integration

* Queue selection
* Context loading
* Note editing
* Orders

End-to-End

Patient

↓

Consultation

↓

Orders

↓

Prescription

↓

End Consultation

↓

Workflow Update

---

# 21. Accessibility

Support:

* Keyboard navigation
* Screen readers
* High contrast mode
* Adjustable font scaling
* Color-blind safe indicators
* Focus management

Accessibility is a core requirement, not an enhancement.

---

# 22. Acceptance Criteria

The Clinical Workspace is complete when:

* Clinicians can complete an encounter without leaving the workspace.
* Patient context loads automatically and remains synchronized.
* Workflow actions update queues in real time through the Workflow Engine.
* Clinical notes, orders, and prescriptions are managed from a unified interface.
* The timeline provides a complete longitudinal view of the encounter.
* AI assistance is embedded contextually without interrupting clinical workflows.
* The workspace meets performance, accessibility, and security requirements defined by the platform standards.

---

# 23. Developer Deliverables

### Backend

* Clinical Workspace Aggregation Service
* Patient Context Service
* Timeline Aggregation Service
* Clinical Notes API
* Order Orchestration API
* Event Subscribers for live updates

### Frontend

* Workspace Shell
* Queue Panel
* Patient Summary Panel
* Clinical Workspace Panel
* Timeline Drawer
* Quick Actions Panel
* AI Assistant Panel
* Shared Zustand stores
* Reusable hooks and service clients

### QA

* Cross-browser testing
* Keyboard navigation validation
* Real-time synchronization tests
* Auto-save resilience tests
* Long-running session testing

### DevOps

* WebSocket/SSE infrastructure for live updates
* Client performance monitoring
* Frontend error telemetry
* Feature flag support for phased rollout

---

# Architect's Note

I think this is the document that truly captures the vision that emerged from the Royan discussions.

The goal is not to build another electronic medical record screen.

The goal is to build a **clinical command center**.

Every piece of information, every workflow action, every diagnostic update, and every intelligent recommendation converges into a single workspace where the clinician can focus on patient care rather than software navigation.

This engineering philosophy directly supports the operational objective we identified during the Royan workflow sessions: **stay on one screen, complete your work, and let the platform coordinate everything else.**

---

## My Recommendation Before SHES-004

Up to now we've been translating one SHAS document into one SHES document.

Starting with **SHES-004**, I recommend we make each engineering specification even more implementation-ready by appending four standardized annexes:

* **Annex A – FastAPI implementation** (routers, services, repositories, dependency injection)
* **Annex B – PostgreSQL schema** (tables, indexes, constraints, relationships)
* **Annex C – React implementation** (component tree, routing, hooks, state stores)
* **Annex D – Sequence diagrams & event flows** (end-to-end interaction from UI through backend and back)

Those annexes will let the backend and frontend agents move almost directly from specification to code while preserving the architectural intent we've spent the last two phases defining.
Perfect.

Now we're entering what I call the **Clinical Operations Layer** of the engineering specifications.

Notice the progression:

* **SHES-001** → Where users work.
* **SHES-002** → How the platform orchestrates work.
* **SHES-003** → How clinicians perform work.

Now we answer the next question:

> **How is clinical data actually captured?**

This is one of the biggest weaknesses of most Hospital Management Systems.

Most systems build forms.

We're not building forms.

We're building a **Clinical Data Capture Framework**.

That distinction is huge.

The goal isn't to make users fill forms.

The goal is to capture healthcare information with the least amount of effort while producing highly structured data.

That philosophy came directly from the Royan meetings:

* Minimize typing
* Dropdowns wherever possible
* Smart defaults
* Auto-filled values
* Medical master data
* Dynamic forms
* Department-specific layouts
* AI assistance

So SHES-004 becomes the engineering implementation of SHAS-004.

---

# SynBot Health Engineering Specification 004

# Smart Clinical Forms & Data Capture Engineering Specification (SCFDES)

**Version:** 1.0

**Project:** SynBot Health

**Engineering Specification:** SHES-004

**Architecture Reference:**

* SHAS-004 – Smart Forms & Clinical Data Entry Standard
* SHAS-005 – Master Data & Reference Standards
* SHAS-015 – Clinical Intelligence Standard

**Status:** Engineering Specification

---

# 1. Purpose

This specification defines the engineering implementation of SynBot Health's Smart Clinical Forms Framework.

Rather than static forms, the platform provides intelligent, metadata-driven, reusable clinical forms capable of adapting to:

* Department
* Encounter
* User Role
* Workflow State
* Clinical Context
* Patient Context

The objective is to maximize structured data capture while minimizing user interaction.

---

# 2. Engineering Philosophy

Traditional HMS

```text
Create Form

↓

User Completes Form

↓

Save
```

SynBot Health

```text
Patient Context

↓

Workflow State

↓

Form Engine

↓

Smart Components

↓

AI Assistance

↓

Validation

↓

Auto Save

↓

Workflow Engine
```

The platform assembles forms dynamically rather than relying on fixed page layouts.

---

# 3. Core Design Principles

The Form Framework shall be:

* Metadata-driven
* Reusable
* Component-based
* Context-aware
* Event-driven
* Auto-saving
* Mobile-friendly
* Offline-capable (future)
* Version-controlled

---

# 4. Engineering Architecture

```text
Clinical Workspace

↓

Smart Form Engine

↓

Form Metadata Service

↓

Master Data Service

↓

Validation Engine

↓

Workflow Engine

↓

Audit Service
```

Forms become consumers of platform services rather than isolated UI components.

---

# 5. Backend Modules

```text
/forms/

controller.py

service.py

metadata_service.py

validation_service.py

template_service.py

autosave_service.py

reference_data_client.py

audit_service.py
```

Every responsibility remains isolated.

---

# 6. Frontend Module Structure

```text
src/

modules/

forms/

components/

controls/

layouts/

hooks/

validators/

schemas/

store/
```

Every clinical form inherits the same framework.

---

# 7. Dynamic Form Engine

Instead of hardcoding fields:

```text
Vitals Form

↓

Metadata

↓

Renderer

↓

React Components

↓

Validation

↓

Submission
```

The UI renders forms from configuration metadata.

This allows departments to introduce new forms without major frontend redevelopment.

---

# 8. Smart Components

The framework shall include reusable controls.

Examples:

## Text Input

Supports

* autocomplete
* spell checking
* abbreviations
* voice input

---

## Numeric Input

Supports

* ranges
* units
* validation
* formatting

---

## Date & Time

Supports

* current timestamp
* encounter timestamp
* timezone awareness

---

## Dropdown

Supports

* search
* grouped options
* keyboard navigation
* lazy loading

---

## Multi-select

Supports

* ICD
* Symptoms
* Allergies
* Diagnoses

---

## Medication Selector

Integrated with Master Data.

Displays

* Generic Name
* Brand Name
* Strength
* Dosage Form
* Availability

---

## Laboratory Selector

Displays

* Category
* Test
* Preparation
* Priority

---

## Imaging Selector

Displays

* Modality
* Study
* Preparation

---

## HMO Selector

Displays

* Provider
* Plan
* Coverage

---

# 9. Metadata Schema

Every field stores metadata.

Example:

```json
{
  "fieldId": "",
  "label": "",
  "component": "",
  "required": true,
  "defaultValue": "",
  "validation": {},
  "masterData": "",
  "workflowVisibility": []
}
```

Forms are defined by metadata rather than frontend code.

---

# 10. Master Data Integration

Every dropdown should originate from SHAS-005 master data.

Examples

ICD

↓

Diagnosis Picker

---

Drug Catalogue

↓

Prescription

---

Laboratory Catalogue

↓

Lab Orders

---

Radiology Catalogue

↓

Imaging Orders

---

Procedure Catalogue

↓

Procedures

Users should never type standardized values when they can be selected.

---

# 11. Clinical Auto-complete

The engine supports:

* ICD search
* Drug search
* Laboratory search
* Imaging search
* Procedures
* Allergies

Autocomplete should return ranked results within milliseconds.

---

# 12. Smart Defaults

Examples

Doctor selected

↓

Current User

---

Department

↓

Current Department

---

Encounter

↓

Current Encounter

---

Date

↓

Current Timestamp

---

Vitals Unit

↓

Configured Standard

The platform fills predictable values automatically.

---

# 13. Conditional Fields

Fields appear dynamically.

Example

```text
Pregnant

↓

Yes

↓

Obstetric Fields

↓

Visible
```

```text
Medication

↓

Insulin

↓

Blood Glucose Monitoring

↓

Visible
```

Visibility rules are metadata-driven.

---

# 14. Validation Engine

Validation occurs:

Client

↓

Immediate

Server

↓

Business Rules

Workflow

↓

State Validation

Master Data

↓

Reference Validation

Validation should be layered rather than duplicated.

---

# 15. Auto-save

Forms auto-save:

* every few seconds
* on field change
* on workflow transition
* before navigation

Recovery should restore unfinished documentation after interruptions.

---

# 16. AI Assistance

SHAS-015 integration provides:

Clinical sentence completion

↓

Diagnosis suggestions

↓

SOAP assistance

↓

ICD recommendations

↓

Drug recommendations

↓

Follow-up suggestions

↓

Documentation completeness checks

AI suggestions remain optional and clearly distinguishable from clinician-entered content.

---

# 17. API Endpoints

```http
GET /forms/template/{templateId}

GET /forms/masterdata/{type}

POST /forms/autosave

POST /forms/validate

POST /forms/submit

GET /forms/history/{encounterId}
```

Templates, reference data, validation, and submissions remain separate concerns.

---

# 18. State Management

Suggested stores:

```text
formStore

metadataStore

masterDataStore

validationStore

autosaveStore

draftStore
```

Drafts and submitted records remain distinct.

---

# 19. Performance Targets

Form rendering

<300 ms

Dropdown search

<150 ms

Auto-save

<250 ms

Validation

<100 ms

Metadata loading

<500 ms

Performance targets should be measured under realistic clinical workloads.

---

# 20. Security

The framework enforces:

* field-level permissions
* role-based visibility
* department restrictions
* encounter ownership
* audit logging

Sensitive fields may be masked or read-only based on user role.

---

# 21. Testing Strategy

### Unit

* Component rendering
* Validation rules
* Metadata parsing

### Integration

* Master data loading
* Auto-save
* Conditional visibility
* Workflow interaction

### End-to-End

* Complete consultation
* Laboratory request
* Prescription entry
* Dynamic field behavior
* Draft recovery

---

# 22. Acceptance Criteria

The Smart Clinical Forms Framework is complete when:

* Forms render from metadata rather than hardcoded layouts.
* Standardized values are selected from governed master data wherever applicable.
* Conditional fields respond automatically to clinical context.
* Auto-save protects work without user intervention.
* Validation is consistent across client and server.
* AI assistance improves documentation without replacing clinician judgment.
* New forms can be introduced through metadata with minimal code changes.

---

# 23. Developer Deliverables

## Backend

* Form Metadata Service
* Template Registry
* Validation Engine
* Auto-save Service
* Reference Data Integration
* Draft Management API

## Frontend

* Dynamic Form Renderer
* Reusable Control Library
* Metadata Loader
* Auto-save Hooks
* Validation Components
* Smart Lookup Components

## QA

* Metadata-driven form tests
* Draft recovery tests
* Validation consistency tests
* Accessibility verification
* Performance testing for large forms

## DevOps

* Metadata configuration deployment
* Feature flag support for new templates
* Monitoring for auto-save failures
* Form rendering performance dashboards

---

# Annex A – FastAPI Implementation

### Suggested Structure

```text
app/
 ├── modules/
 │    ├── forms/
 │    │     ├── router.py
 │    │     ├── service.py
 │    │     ├── metadata.py
 │    │     ├── validation.py
 │    │     ├── autosave.py
 │    │     ├── repository.py
 │    │     ├── schemas.py
 │    │     └── dependencies.py
```

---

# Annex B – PostgreSQL Schema

Core tables:

* `form_template`
* `form_template_version`
* `form_section`
* `form_field`
* `form_field_rule`
* `form_draft`
* `form_submission`
* `form_validation_log`

Indexes:

* `encounter_id`
* `patient_id`
* `template_id`
* `workflow_state`
* `updated_at`

---

# Annex C – React Implementation

Suggested component hierarchy:

```text
ClinicalWorkspace
 ├── DynamicFormRenderer
 │     ├── FormSection
 │     │     ├── SmartInput
 │     │     ├── SmartSelect
 │     │     ├── SmartLookup
 │     │     ├── MedicationPicker
 │     │     ├── ICDPicker
 │     │     └── ValidationBanner
 ├── AutosaveIndicator
 ├── DraftRecoveryBanner
 └── AIAssistantPanel
```

---

# Annex D – Sequence Flow

```text
Doctor Opens Consultation

↓

Workspace Loads

↓

Metadata Retrieved

↓

Patient Context Loaded

↓

Master Data Loaded

↓

Dynamic Form Rendered

↓

Doctor Documents Findings

↓

Auto-save Executes

↓

Validation Runs

↓

Doctor Ends Consultation

↓

Workflow Engine Advances Encounter

↓

Audit Recorded
```

---

# Architect's Note

This specification embodies one of the strongest themes from the Royan Hospital workshops:

> **Clinicians should spend their time treating patients—not fighting software.**

By making forms metadata-driven, master-data powered, auto-saving, and deeply integrated with the workflow engine, SynBot Health moves away from traditional "data entry screens" toward **clinical productivity tools**.

Unlike many Hospital Management Systems where each department builds its own forms independently, this framework creates a single engineering foundation that every department inherits. That means a new specialty—Cardiology, Oncology, Maternity, or ICU—can introduce new documentation templates primarily through metadata and governed reference data rather than extensive frontend redevelopment.

---

## Engineering Progress

* ✅ SHES-001 – Universal Department Workspace
* ✅ SHES-002 – Universal Workflow Engine
* ✅ SHES-003 – Clinical Workspace
* ✅ **SHES-004 – Smart Clinical Forms & Data Capture**

With these four specifications complete, we've defined the **presentation layer**, **orchestration layer**, **clinical interaction layer**, and **data capture layer**. The next logical engineering specification is **SHES-005 – Master Data & Reference Services Engineering Specification**, which will define how ICD codes, drug catalogs, laboratory catalogs, radiology catalogs, HMO plans, tariffs, procedures, and all governed reference datasets are modeled, synchronized, cached, versioned, and exposed consistently across the entire SynBot Health platform.
Let's get it. ☕

This document is probably **the most underestimated document** in the entire platform.

Yesterday, while writing SHES-004, something became very obvious.

The Smart Forms Engine only works because **Master Data exists**.

Without Master Data...

* No ICD autocomplete
* No Drug autocomplete
* No Laboratory catalogue
* No Radiology catalogue
* No Procedure catalogue
* No Tariffs
* No HMOs
* No Dropdowns
* No AI recommendations
* No Standardization

Which means...

> **Master Data isn't supporting the HMS.**

**Master Data IS the HMS.**

I honestly think this should become one of the largest engineering specifications in the project because nearly every other module depends on it.

This is basically our **Healthcare Knowledge Layer**.

---

# SynBot Health Engineering Specification 005

# Master Data & Reference Services Engineering Specification (MDRSES)

**Version:** 1.0

**Project:** SynBot Health

**Engineering Specification:** SHES-005

**Architecture Reference**

* SHAS-005 — Master Data & Reference Standards
* SHAS-004 — Smart Clinical Forms
* SHAS-015 — Clinical Intelligence

**Status:** Engineering Specification

---

# 1. Purpose

The Master Data & Reference Services define the engineering implementation of every governed reference dataset used throughout SynBot Health.

Rather than allowing departments to maintain independent copies of reference information, the platform provides a centralized Master Data Service responsible for publishing standardized healthcare reference data across all modules.

Master Data becomes the authoritative source for standardized terminology, catalogues, classifications, tariffs, organizational configuration, and reusable reference values.

---

# 2. Engineering Philosophy

Traditional HMS

```text
Laboratory

↓

Own List

Pharmacy

↓

Own Drug List

Billing

↓

Own Tariffs

Radiology

↓

Own Procedures
```

Everyone owns different copies.

Eventually...

Nothing matches.

---

SynBot Health

```text
Master Data Service

↓

Clinical Services

↓

Financial Services

↓

Workflow Engine

↓

Forms Engine

↓

AI Engine

↓

Reports
```

One source.

Everyone consumes.

Nobody duplicates.

---

# 3. Responsibilities

Master Data owns:

* Clinical reference data
* Financial reference data
* Organizational configuration
* Geographic reference data
* Lookup catalogues
* Version control
* Effective dates
* Synchronization
* Validation

Master Data does NOT own patient information.

---

# 4. Engineering Architecture

```text
Admin Portal

↓

Master Data Service

↓

Validation Engine

↓

Version Manager

↓

Reference Cache

↓

API Layer

↓

Consumers
```

Every service reads from Master Data.

No service maintains private copies.

---

# 5. Backend Modules

```text
/master-data/

router.py

service.py

catalog_service.py

version_service.py

cache_service.py

validation_service.py

repository.py

schemas.py

events.py
```

Each catalogue is implemented as a plugin.

---

# 6. Reference Domains

Master Data shall support:

Clinical

Financial

Operational

Administrative

Regulatory

Infrastructure

Each domain contains multiple catalogues.

---

# 7. Clinical Catalogues

Examples include:

ICD

SNOMED (future)

LOINC (future)

Laboratory Tests

Radiology Studies

Medications

Drug Strengths

Dosage Forms

Administration Routes

Allergies

Diagnoses

Procedures

Symptoms

Vaccines

Body Sites

Specimen Types

Observation Types

Clinical Templates

These datasets support nearly every clinical workflow.

---

# 8. Financial Catalogues

Examples

Tariffs

Service Prices

Procedure Prices

Corporate Prices

HMO Prices

Taxes

Currencies

Discount Types

Revenue Centers

Billing Codes

---

# 9. Operational Catalogues

Examples

Departments

Clinics

Buildings

Floors

Rooms

Beds

Machines

Laboratories

Radiology Equipment

Dialysis Machines

Theatres

Appointment Types

Shift Types

Queues

---

# 10. Administrative Catalogues

Examples

Roles

Permissions

Users

Organizations

Branches

Titles

Employment Types

Professional Licenses

Specialties

Qualifications

---

# 11. Regulatory Catalogues

Examples

Countries

States

Cities

Nationalities

Languages

Religions

Marital Status

Insurance Providers

Government Schemes

Medical Councils

---

# 12. Catalogue Structure

Every catalogue follows:

```text
Catalogue

↓

Category

↓

Item

↓

Attributes

↓

Relationships

↓

Version

↓

Status
```

This structure allows all catalogues to share a common implementation model.

---

# 13. Master Data Entity

Every catalogue item contains:

```json
{
  "id": "",
  "code": "",
  "name": "",
  "description": "",
  "category": "",
  "status": "ACTIVE",
  "effectiveFrom": "",
  "effectiveTo": "",
  "version": ""
}
```

Additional attributes extend this base model.

---

# 14. Version Management

Every catalogue supports:

Draft

↓

Review

↓

Approved

↓

Published

↓

Deprecated

↓

Archived

Nothing is deleted.

Historical encounters continue referencing historical versions.

---

# 15. Effective Dating

Every record supports:

Valid From

↓

Valid Until

↓

Version

↓

Replacement

Example

ICD revision

↓

Previous encounters

↓

Remain unchanged

↓

New encounters

↓

Use latest version

---

# 16. Validation Engine

Master Data validates:

Duplicate Codes

↓

Duplicate Names

↓

Relationship Integrity

↓

Required Fields

↓

Version Conflicts

↓

Reference Integrity

Validation occurs before publication.

---

# 17. API Endpoints

```http
GET /master/catalogues

GET /master/catalogue/{type}

GET /master/item/{id}

GET /master/search

POST /master/publish

POST /master/version

POST /master/archive
```

Search endpoints should support pagination, filtering, and fuzzy matching.

---

# 18. Search Engine

Every catalogue supports:

Search

Autocomplete

Synonyms

Aliases

Abbreviations

Ranking

Examples

Search:

"Para"

↓

Paracetamol

↓

Acetaminophen

↓

Related strengths

↓

Related dosage forms

---

# 19. Cache Layer

Master Data should be cached aggressively.

Example

```text
PostgreSQL

↓

Redis

↓

API

↓

React

↓

Dropdown
```

Large catalogues should never require repeated database reads.

---

# 20. Event Model

Publishing a catalogue generates:

MasterDataPublished

↓

Consumers Refresh Cache

↓

Search Rebuilt

↓

AI Updated

↓

Audit Logged

Everything updates automatically.

---

# 21. AI Integration

SHAS-015 consumes Master Data.

Examples

ICD Suggestions

↓

Drug Suggestions

↓

Procedure Suggestions

↓

Laboratory Suggestions

↓

Radiology Suggestions

↓

Clinical Terminology

AI never invents standardized terminology.

It references Master Data.

---

# 22. Frontend Components

Reusable components

SmartLookup

SmartDropdown

TreeSelector

HierarchyPicker

SearchDialog

TagSelector

ReferenceBrowser

CatalogueEditor

VersionHistory

RelationshipViewer

These components are shared platform-wide.

---

# 23. Security

Supports:

Read Permissions

Edit Permissions

Approval Permissions

Publish Permissions

Archive Permissions

Reference data governance should follow separation-of-duties principles.

---

# 24. Performance Targets

Autocomplete

<100 ms

Catalogue Search

<150 ms

Publish

<2 sec

Cache Refresh

<1 sec

Dropdown Load

<200 ms

These targets should be monitored continuously.

---

# 25. Testing Strategy

Unit

* Validation rules
* Versioning
* Search ranking

Integration

* Cache invalidation
* Publish workflow
* API consistency

Load

* Million-record search
* Concurrent autocomplete
* Cache warm-up

Regression

* Historical version integrity
* Consumer compatibility
* Backward compatibility

---

# 26. Acceptance Criteria

The Master Data Service is complete when:

* Every department consumes centralized reference data.
* No duplicate reference datasets exist across services.
* Versioning preserves historical integrity.
* Autocomplete and search meet performance targets.
* Catalogue publication updates consuming services automatically.
* AI, Forms, Billing, Workflow, and Reporting use governed reference data.
* Master data changes are fully auditable.

---

# 27. Developer Deliverables

## Backend

* Master Data Service
* Catalogue Registry
* Version Manager
* Search Service
* Cache Layer
* Event Publisher
* Validation Engine

---

## Frontend

* SmartLookup
* SmartDropdown
* Catalogue Management UI
* Version History UI
* Relationship Explorer
* Search Components

---

## QA

* Version migration tests
* Search accuracy validation
* Cache consistency tests
* Approval workflow tests
* Performance benchmarks

---

## DevOps

* Redis deployment
* Search indexing jobs
* Cache monitoring
* Publish pipeline
* Backup and recovery for reference datasets

---

# Annex A — FastAPI Implementation

```text
app/
└── modules/
    └── master_data/
        ├── router.py
        ├── service.py
        ├── catalog.py
        ├── search.py
        ├── version.py
        ├── validation.py
        ├── cache.py
        ├── repository.py
        ├── events.py
        └── schemas.py
```

Each catalogue inherits from a shared `BaseCatalogService` to minimize duplicate logic.

---

# Annex B — PostgreSQL Schema

### Core Tables

```text
master_catalog

master_category

master_item

master_item_attribute

master_relationship

master_version

master_publish_history

master_alias

master_synonym
```

### Recommended Indexes

* `(catalog_type, code)`
* `(catalog_type, name)`
* `status`
* `effective_from`
* `effective_to`
* Full-text index for search fields

---

# Annex C — React Implementation

```text
MasterDataModule
│
├── CatalogBrowser
├── CatalogEditor
├── SearchPanel
├── SmartLookup
├── SmartDropdown
├── RelationshipViewer
├── VersionHistory
├── PublishWizard
└── ApprovalQueue
```

These components should be reusable by Clinical Workspace, Billing, Pharmacy, Laboratory, Radiology, and Administration modules.

---

# Annex D — Sequence Flow

```text
Administrator Updates Drug Catalogue

↓

Validation Engine

↓

Approval Workflow

↓

Publish

↓

Master Data Event Published

↓

Redis Cache Refreshed

↓

Search Index Updated

↓

Clinical Forms Updated

↓

Pharmacy Updated

↓

AI Knowledge Refreshed

↓

Audit Recorded
```

No consumer service should require a restart to receive newly published reference data.

---

# Architect's Note

This specification establishes the **Healthcare Knowledge Layer** of SynBot Health.

Everything we've designed so far depends on it:

* **SHES-001** renders workspaces using master data labels and configuration.
* **SHES-002** uses master data to evaluate workflow rules and route tasks.
* **SHES-003** presents governed terminology inside the clinical workspace.
* **SHES-004** renders metadata-driven forms powered by centralized reference datasets.
* **SHES-005** becomes the authoritative source from which all of those capabilities derive their standardized knowledge.

From an engineering perspective, this is one of the highest-leverage services in the platform. If implemented well, adding a new diagnosis catalogue, tariff schedule, laboratory test, HMO contract, or specialty module becomes a **configuration exercise rather than a software rewrite**.

---

## Engineering Progress

* ✅ SHES-001 – Universal Department Workspace
* ✅ SHES-002 – Universal Workflow Engine
* ✅ SHES-003 – Clinical Workspace
* ✅ SHES-004 – Smart Clinical Forms & Data Capture
* ✅ **SHES-005 – Master Data & Reference Services**

### Looking Ahead

With SHES-005 complete, we've established the platform's foundational engineering layer. The next logical specification is **SHES-006 – Department Framework & Workspace Composition Engineering Specification**, where we'll define how every department (OPD, Laboratory, Pharmacy, Theatre, Billing, etc.) inherits a common engineering framework while injecting only its own business logic, components, queues, actions, and dashboards. This will become the engineering blueprint that keeps all current and future departments consistent across SynBot Health.
Absolutely. I actually think **SHES-006** is where the engineering architecture starts becoming elegant.

Up until now we've built:

* How the workspace works
* How workflows work
* How clinicians work
* How forms work
* How master data works

Now we answer the question every developer will ask:

> **"How do I build a new department without rewriting the application?"**

This is where most HMS projects fail.

Every department ends up becoming its own mini application.

One screen for OPD.

One screen for Pharmacy.

Another for Laboratory.

Another for Theatre.

Different layouts.

Different code.

Different state management.

Different API calls.

Different logic.

Eventually...

Nothing looks alike.

Nothing is reusable.

We are not going to build SynBot Health that way.

Every department should inherit one framework.

Departments should configure...

...not reinvent.

This specification becomes one of the most important backend/frontend documents because it defines how every future department is assembled.

---

# SynBot Health Engineering Specification 006

# Department Framework & Workspace Composition Engineering Specification (DFWCES)

**Version:** 1.0

**Project:** SynBot Health

**Engineering Specification:** SHES-006

**Architecture References**

* SHAS-001 — Universal Department Workspace
* SHAS-006 — Department Implementation Standard
* SHES-001 — Universal Department Workspace Engineering Specification
* SHES-002 — Workflow Engine Engineering Specification
* SHES-003 — Clinical Workspace Engineering Specification

**Status:** Engineering Specification

---

# 1. Purpose

The Department Framework defines the reusable engineering architecture used to implement every operational department within SynBot Health.

Rather than creating separate applications for OPD, Laboratory, Pharmacy, Billing, Theatre, and future departments, every department inherits a shared framework and supplies only its specialized business components.

The framework guarantees architectural consistency, reduces duplicated code, simplifies maintenance, and accelerates development of new clinical and administrative services.

---

# 2. Engineering Philosophy

Traditional HMS

```text
OPD

↓

Independent UI

↓

Independent APIs

↓

Independent Logic
```

```text
Laboratory

↓

Different UI

↓

Different APIs

↓

Different Logic
```

Eventually...

Everything diverges.

---

SynBot Health

```text
Department Framework

↓

Configuration

↓

Shared Components

↓

Department Modules

↓

Operational Workspace
```

Every department inherits.

No department starts from scratch.

---

# 3. Responsibilities

The Department Framework owns:

* Workspace composition
* Shared layouts
* Queue integration
* Patient context integration
* Workflow integration
* Security integration
* Event subscriptions
* Dashboard framework

Departments own:

* Business rules
* Clinical actions
* Specialized forms
* Department KPIs
* Reports
* Domain services

---

# 4. Engineering Architecture

```text
Department Module

↓

Department Framework

↓

Workspace Framework

↓

Workflow Engine

↓

Master Data

↓

Notification Engine

↓

Audit Engine
```

The framework orchestrates.

Departments specialize.

---

# 5. Department Composition Model

Every department consists of:

```text
Department

↓

Configuration

↓

Workspace

↓

Queues

↓

Forms

↓

Actions

↓

Reports

↓

Dashboard

↓

Services
```

Everything follows one composition model.

---

# 6. Backend Module Structure

```text
/modules/

department/

base/

department_factory.py

department_registry.py

department_loader.py

department_config.py

workspace_factory.py
```

Each department extends the BaseDepartment class.

---

# 7. Department Registration

Every department registers itself.

Example

```python
DepartmentRegistry.register(
    code="OPD",
    workspace=OPDWorkspace,
    services=[...],
    actions=[...]
)
```

Registration enables runtime discovery.

---

# 8. Base Department Contract

Every department implements:

```text
initialize()

loadWorkspace()

loadQueue()

loadActions()

loadDashboard()

loadReports()

validateTransition()

publishEvents()
```

This contract ensures consistent behavior across all departments.

---

# 9. Workspace Composition

Each workspace is assembled dynamically.

```text
Framework

↓

Header

↓

Queue

↓

Patient Context

↓

Department Components

↓

Actions

↓

Timeline

↓

Notifications
```

Only the department-specific panel changes.

---

# 10. Department Configuration

Each department exposes configuration such as:

```yaml
department:
  code: OPD
  queue: opd_queue
  workspace: consultation
  actions:
    - call_patient
    - start_consultation
    - end_consultation
  dashboard:
    - waiting_patients
    - average_wait
```

Configuration drives behavior instead of hardcoded logic.

---

# 11. Shared Components

Inherited automatically:

* QueuePanel
* PatientContextPanel
* Timeline
* Notification Center
* Action Bar
* Header
* Breadcrumb
* Search
* Status Bar

Departments rarely replace shared components.

---

# 12. Department Components

Injected dynamically.

Examples

OPD

↓

Consultation Workspace

Laboratory

↓

Specimen Processing Panel

Radiology

↓

Imaging Workspace

Pharmacy

↓

Dispensing Workspace

Billing

↓

Invoice Workspace

The framework decides placement.

Departments provide content.

---

# 13. Queue Integration

Every department receives:

```text
Queue Service

↓

Department Queue

↓

Filtered View

↓

Live Updates
```

Queue behavior remains standardized.

---

# 14. Dashboard Framework

Every department dashboard inherits:

KPIs

↓

Charts

↓

Widgets

↓

Alerts

↓

Recent Activity

↓

Pending Work

Departments only define widget content.

---

# 15. Action Framework

Actions are metadata-driven.

Example

```json
{
  "action": "start_consultation",
  "icon": "play",
  "workflow": "consultation_start",
  "permission": "consultation.start"
}
```

The framework renders actions automatically.

---

# 16. Security Integration

Every department inherits:

* Role validation
* Department authorization
* Permission checks
* Feature flags
* Audit logging

Security behavior remains consistent.

---

# 17. Event Integration

Every department subscribes to:

* Queue Updated
* Workflow Updated
* Patient Assigned
* Notification Created
* Task Created

Departments may subscribe to additional domain events.

---

# 18. State Management

Recommended stores:

```text
departmentStore

workspaceStore

queueStore

dashboardStore

actionStore

reportStore
```

State remains modular.

---

# 19. API Structure

```http
GET /department/{code}

GET /department/{code}/workspace

GET /department/{code}/dashboard

GET /department/{code}/reports

POST /department/{code}/action

GET /department/{code}/configuration
```

Department APIs expose composition rather than business logic.

---

# 20. Performance Targets

Workspace composition

<500 ms

Department load

<1 second

Dashboard refresh

<2 seconds

Queue update

<500 ms

Configuration load

<200 ms

---

# 21. Testing Strategy

### Unit

* Department registration
* Configuration loading
* Workspace composition

### Integration

* Queue integration
* Workflow actions
* Dashboard rendering

### End-to-End

* Switch departments
* Execute actions
* Dashboard updates
* Event propagation

---

# 22. Acceptance Criteria

The Department Framework is complete when:

* Every department inherits the same engineering framework.
* New departments can be added primarily through configuration and specialized modules.
* Shared components are reused consistently.
* Department-specific logic remains isolated from framework logic.
* Queue, workflow, notifications, and security integrate seamlessly.
* Performance targets are met across all supported departments.

---

# 23. Developer Deliverables

## Backend

* BaseDepartment abstract class
* Department Registry
* Workspace Factory
* Configuration Loader
* Dashboard Engine
* Action Registry

## Frontend

* Department Shell
* Dynamic Workspace Composer
* Widget Framework
* Shared Layout Components
* Department Configuration Loader

## QA

* Framework compliance tests
* Department onboarding tests
* Configuration validation tests
* Cross-department regression tests

## DevOps

* Feature flag configuration
* Department deployment validation
* Runtime health checks
* Configuration integrity monitoring

---

# Annex A – FastAPI Implementation

```text
app/
└── modules/
    └── departments/
        ├── base.py
        ├── registry.py
        ├── factory.py
        ├── config_loader.py
        ├── router.py
        ├── service.py
        ├── workspace.py
        └── dashboard.py
```

Every department package (e.g., `opd`, `laboratory`, `pharmacy`) inherits from this shared framework.

---

# Annex B – PostgreSQL Schema

Core framework tables:

* `department`
* `department_configuration`
* `department_workspace`
* `department_widget`
* `department_action`
* `department_dashboard`
* `department_feature_flag`

Indexes:

* `department_code`
* `workspace_type`
* `feature_flag`
* `status`

These tables configure department behavior rather than storing transactional clinical data.

---

# Annex C – React Implementation

```text
DepartmentShell
│
├── Header
├── QueuePanel
├── PatientContextPanel
├── DynamicWorkspace
│     ├── DepartmentComponent
│     ├── ActionPanel
│     └── Timeline
├── DashboardWidgets
└── NotificationCenter
```

The `DepartmentShell` is the reusable foundation; each department injects only its specialized components.

---

# Annex D – Sequence Flow

```text
User Opens Department

↓

Department Registry

↓

Configuration Loaded

↓

Workspace Composed

↓

Queue Loaded

↓

Patient Context Ready

↓

Department Components Mounted

↓

Workflow Subscription Active

↓

Workspace Ready
```

The framework composes the department dynamically instead of relying on hardcoded screens.

---

# Architect's Note

I think this specification is one of the defining engineering decisions for SynBot Health.

Instead of treating departments as independent applications, we treat them as **plug-ins** that inherit a common operational framework.

That means:

* Building **Cardiology** becomes adding a new department module—not creating a new application.
* Building **ICU**, **Oncology**, **Dental**, or **Maternity** follows the same engineering contract.
* Shared capabilities—workflow, security, notifications, patient context, AI, and auditing—are inherited automatically.

This dramatically reduces engineering effort while ensuring that every department feels like part of a single, coherent platform.

---

# Engineering Progress

## Core Platform Specifications

* ✅ SHES-001 – Universal Department Workspace
* ✅ SHES-002 – Universal Workflow Engine
* ✅ SHES-003 – Clinical Workspace
* ✅ SHES-004 – Smart Clinical Forms & Data Capture
* ✅ SHES-005 – Master Data & Reference Services
* ✅ **SHES-006 – Department Framework & Workspace Composition**

At this point, we've completed what I would call the **Platform Engineering Foundation**. Every subsequent specification can build on these six documents rather than redefining core behavior.

## Recommendation for SHES-007

The next specification should be **SHES-007 – Event Bus, Messaging & Notification Engineering Specification**.

This will define the platform's nervous system: event schemas, message broker architecture, asynchronous processing, notification delivery (in-app, email, SMS, push), retries, dead-letter queues, idempotency, and event contracts. Since virtually every workflow in SynBot Health depends on reliable event propagation, it is the natural next engineering layer before we move into more specialized services like reporting, analytics, or AI orchestration.
Perfect. This is exactly where the platform starts feeling like an enterprise distributed system instead of a CRUD application.

I actually think this document is second only to the Workflow Engine.

Here's why.

Yesterday we established:

> **Users do work.**

The Workflow Engine established:

> **The platform coordinates work.**

Now we define **how the platform talks to itself.**

This is one of the biggest architectural differences between a small application and an enterprise platform.

---

## Traditional HMS

Doctor finishes consultation

↓

Update Database

↓

Done

---

## SynBot Health

Doctor finishes consultation

↓

Workflow Engine

↓

ConsultationCompleted Event

↓

Laboratory Queue

↓

Billing Engine

↓

Audit Engine

↓

Timeline Engine

↓

AI Engine

↓

Notification Engine

↓

Dashboard Engine

↓

Analytics Engine

↓

Future Integrations

One action.

Many consumers.

Nobody knows about each other.

That is enterprise architecture.

I also think this is where we introduce one of the biggest engineering principles for SynBot:

> **Everything important is an Event.**

---

# SynBot Health Engineering Specification 007

# Event Bus, Messaging & Notification Engineering Specification (EBMNES)

**Version:** 1.0

**Project:** SynBot Health

**Engineering Specification:** SHES-007

**Architecture References**

* SHAS-007 — Workflow Automation Standard
* SHAS-008 — Event & Notification Standard
* SHES-002 — Workflow Engine
* SHES-006 — Department Framework

**Status:** Engineering Specification

---

# 1. Purpose

The Event Bus, Messaging & Notification Framework defines the asynchronous communication architecture for SynBot Health.

Rather than allowing services to communicate directly, every significant business activity generates events that are published through a centralized Event Bus.

Services subscribe only to events relevant to their responsibilities.

This architecture promotes scalability, loose coupling, resilience, and future extensibility.

---

# 2. Engineering Philosophy

Traditional Systems

```text
Doctor Ends Consultation

↓

Laboratory API

↓

Billing API

↓

Notification API

↓

Audit API
```

One service knows everyone.

---

SynBot Health

```text
Doctor Ends Consultation

↓

Workflow Engine

↓

ConsultationCompleted Event

↓

Event Bus

↓

Subscribers
```

Nobody knows anybody.

Everybody knows Events.

---

# 3. Core Responsibilities

The Event Platform owns:

* Event publishing
* Event delivery
* Event persistence
* Retry management
* Dead-letter queues
* Notification routing
* Subscription management
* Delivery guarantees
* Event replay

The Event Platform does NOT own business logic.

---

# 4. Architecture

```text
Workflow Engine

↓

Event Publisher

↓

Message Broker

↓

Event Bus

↓

Subscribers

↓

Notification Engine

↓

Audit

↓

Analytics

↓

AI

↓

Dashboards
```

---

# 5. Backend Modules

```text
/modules/

events/

publisher.py

subscriber.py

dispatcher.py

broker.py

notification.py

retry.py

dead_letter.py

schemas.py

router.py
```

---

# 6. Event Lifecycle

```text
Business Action

↓

Domain Event Created

↓

Validation

↓

Publish

↓

Broker

↓

Subscribers

↓

Processing

↓

Acknowledgement

↓

Audit
```

Every event has one lifecycle.

---

# 7. Event Categories

Clinical

Operational

Financial

Administrative

Security

Integration

Infrastructure

Analytics

---

# 8. Clinical Events

Examples

PatientRegistered

VitalsRecorded

ConsultationStarted

ConsultationCompleted

DiagnosisRecorded

PrescriptionCreated

MedicationDispensed

LabRequested

LabCompleted

RadiologyCompleted

PatientAdmitted

PatientDischarged

---

# 9. Financial Events

InvoiceCreated

PaymentReceived

RefundProcessed

ClaimSubmitted

ClaimApproved

DiscountApplied

OutstandingBalanceCreated

---

# 10. Operational Events

QueueUpdated

DepartmentLoaded

TaskCreated

TaskCompleted

WorkflowTransitioned

DashboardRefreshed

---

# 11. Security Events

LoginSucceeded

LoginFailed

RoleChanged

PermissionUpdated

EmergencyAccessGranted

PasswordReset

SensitiveRecordViewed

---

# 12. Event Schema

Every event contains:

```json
{
  "eventId":"",
  "eventType":"",
  "aggregateId":"",
  "aggregateType":"",
  "encounterId":"",
  "patientId":"",
  "performedBy":"",
  "department":"",
  "occurredAt":"",
  "version":"",
  "payload":{}
}
```

Versioning allows event evolution without breaking subscribers.

---

# 13. Event Broker

Recommended architecture:

```text
Workflow

↓

Publisher

↓

RabbitMQ / Kafka

↓

Exchange

↓

Queues

↓

Consumers
```

The broker implementation should remain abstract so that RabbitMQ, Kafka, Azure Service Bus, or another compatible broker can be substituted without changing domain logic.

---

# 14. Topic Structure

Suggested topics:

```text
clinical.*

workflow.*

financial.*

laboratory.*

radiology.*

pharmacy.*

billing.*

notifications.*

audit.*

analytics.*

security.*
```

Consumers subscribe using routing patterns.

---

# 15. Event Consumers

Examples

ConsultationCompleted

↓

Laboratory

↓

Billing

↓

Timeline

↓

Analytics

↓

AI

↓

Notifications

↓

Audit

Every consumer works independently.

---

# 16. Notification Engine

Notification Types

* In-App
* Email
* SMS
* Push Notification
* Internal Alert
* Dashboard Badge

Delivery channels are configurable per event type and recipient role.

---

# 17. Notification Routing

```text
Event

↓

Notification Rules

↓

Role Resolution

↓

User Resolution

↓

Delivery Channel

↓

Send

↓

Delivery Status

↓

Audit
```

Rules remain configuration-driven rather than hardcoded.

---

# 18. Delivery Guarantees

Every event supports:

* At-least-once delivery
* Idempotent consumption
* Retry on transient failure
* Delivery acknowledgement
* Failure tracking

Consumers must safely process duplicate deliveries.

---

# 19. Dead Letter Queue (DLQ)

If an event cannot be processed:

```text
Consumer Failure

↓

Retry Policy

↓

Max Attempts Reached

↓

Dead Letter Queue

↓

Operations Alert

↓

Replay (when resolved)
```

No event should disappear silently.

---

# 20. Retry Strategy

Suggested policy:

Attempt 1

Immediate

↓

Attempt 2

5 seconds

↓

Attempt 3

30 seconds

↓

Attempt 4

2 minutes

↓

DLQ

Retry intervals should be configurable.

---

# 21. Event Replay

Support replay by:

* Event ID
* Encounter
* Patient
* Date Range
* Event Type

Replay is restricted to authorized administrative users and preserves audit history.

---

# 22. Event Store

Persist:

* Raw event
* Metadata
* Delivery history
* Subscriber status
* Retry count
* Processing duration

The event store supports troubleshooting, analytics, and replay.

---

# 23. Frontend Integration

Frontend subscribes to:

* Queue updates
* Workflow changes
* Notifications
* Laboratory completion
* Radiology completion
* Billing updates
* Critical alerts

Updates should use WebSockets or Server-Sent Events (SSE), with graceful fallback strategies where appropriate.

---

# 24. API Endpoints

```http
GET /events

GET /events/{eventId}

GET /events/replay

POST /events/publish

GET /notifications

POST /notifications/read

GET /subscriptions
```

Operational endpoints should be secured and role-aware.

---

# 25. State Management

Suggested frontend stores:

```text
eventStore

notificationStore

subscriptionStore

liveUpdateStore

alertStore
```

Stores consume real-time events without coupling to business logic.

---

# 26. Performance Targets

Event publish

<50 ms

Broker delivery

<100 ms

Consumer acknowledgement

<300 ms

Notification creation

<500 ms

UI update

<1 second

---

# 27. Security

Every event supports:

* Digital event identity
* Audit trail
* Authorization checks for replay
* Payload validation
* Sensitive field masking (where required)

Protected health information should only be included in event payloads when necessary for downstream processing.

---

# 28. Testing Strategy

### Unit

* Event serialization
* Schema validation
* Routing logic
* Retry policy

### Integration

* Publisher → Broker → Consumer
* Notification generation
* Event replay
* DLQ handling

### Load

* High-volume event bursts
* Concurrent consumers
* Queue saturation
* Recovery after broker restart

### Chaos

* Broker outage
* Consumer crash
* Duplicate delivery
* Network partition
* Delayed acknowledgements

---

# 29. Acceptance Criteria

The Event Platform is complete when:

* All major business activities generate domain events.
* Services communicate through events rather than direct coupling where asynchronous processing is appropriate.
* Notifications are generated from configurable event rules.
* Failed deliveries are retried and ultimately captured in the Dead Letter Queue.
* Event replay supports operational recovery.
* Subscribers remain independent of publishers.
* Performance and reliability targets are consistently achieved.

---

# 30. Developer Deliverables

## Backend

* Event Publisher
* Event Dispatcher
* Broker Abstraction
* Notification Service
* Retry Manager
* Dead Letter Queue Processor
* Event Store
* Subscription Registry

## Frontend

* Live Event Client
* Notification Center
* Real-Time Badge System
* WebSocket/SSE Manager
* Event Status Indicators

## QA

* End-to-end event flow validation
* Broker resilience testing
* Duplicate delivery testing
* Replay validation
* Notification correctness

## DevOps

* Message broker deployment
* Queue monitoring dashboards
* Dead Letter Queue monitoring
* Consumer lag metrics
* Broker backup and disaster recovery

---

# Annex A – FastAPI Implementation

```text
app/
└── modules/
    └── events/
        ├── publisher.py
        ├── subscriber.py
        ├── dispatcher.py
        ├── broker.py
        ├── notification.py
        ├── replay.py
        ├── dlq.py
        ├── schemas.py
        └── router.py
```

The broker interface should be dependency-injected so that infrastructure choices remain interchangeable.

---

# Annex B – PostgreSQL Schema

Core tables:

* `event_store`
* `event_subscription`
* `event_delivery`
* `notification`
* `notification_delivery`
* `dead_letter_event`
* `event_replay_log`

Recommended indexes:

* `event_type`
* `aggregate_id`
* `encounter_id`
* `patient_id`
* `occurred_at`
* `delivery_status`

---

# Annex C – React Implementation

```text
RealtimeProvider
│
├── EventClient
├── NotificationCenter
├── AlertPanel
├── LiveBadge
├── SubscriptionManager
└── ConnectionStatus
```

The `RealtimeProvider` should expose a unified interface to the rest of the application so individual components never manage socket connections directly.

---

# Annex D – End-to-End Sequence Flow

```text
Doctor Clicks "End Consultation"

↓

Workflow Engine

↓

ConsultationCompleted Event Published

↓

Message Broker

↓

Subscribers

├── Laboratory Queue Updated
├── Billing Charge Created
├── Audit Entry Recorded
├── Timeline Updated
├── AI Context Refreshed
├── Notification Sent
└── Dashboard Metrics Updated

↓

Frontend Receives Live Update

↓

Queue Automatically Refreshes
```

This sequence captures the engineering vision we've been building since the Royan sessions: **the clinician performs one action, and the platform coordinates everything else**.

---

# Architect's Note

I consider **SHES-007** the **digital nervous system** of SynBot Health.

Combined with:

* **SHES-002** (Workflow Engine) — *decides what should happen*.
* **SHES-007** (Event Platform) — *tells the platform that it happened*.

Together, they eliminate tight coupling between services and allow SynBot Health to grow organically. New capabilities—AI modules, analytics, external integrations, wearable devices, government reporting, or additional departments—can subscribe to existing events without forcing changes to the systems already in production.

## Engineering Progress

### Platform Foundation

* ✅ SHES-001 – Universal Department Workspace
* ✅ SHES-002 – Universal Workflow Engine
* ✅ SHES-003 – Clinical Workspace
* ✅ SHES-004 – Smart Clinical Forms & Data Capture
* ✅ SHES-005 – Master Data & Reference Services
* ✅ SHES-006 – Department Framework & Workspace Composition
* ✅ **SHES-007 – Event Bus, Messaging & Notification**

At this stage, the core platform infrastructure is taking shape: presentation, workflow orchestration, data capture, shared reference services, department composition, and asynchronous communication all have engineering specifications. The next logical step is **SHES-008 – Reporting, Analytics & Operational Intelligence Engineering Specification**, where we'll define how transactional data, events, and audit trails are transformed into operational dashboards, executive reporting, quality metrics, and AI-ready analytical datasets. That specification will complete the platform's feedback loop by turning operational activity into actionable insight.
Perfect.

I actually think **SHES-008** is where SynBot Health officially stops being "an HMS" and starts becoming **a Hospital Intelligence Platform**.

This document is not about reports.

It's about **decision support**.

That's a huge distinction.

---

## Traditional HMS

Doctor enters data.

↓

Database stores data.

↓

Monthly report.

↓

Management reads report.

---

## SynBot Health

Doctor enters data.

↓

Workflow Engine

↓

Event Bus

↓

Analytics Pipeline

↓

Operational Dashboards

↓

Department KPIs

↓

Executive KPIs

↓

AI Predictions

↓

Continuous Improvement

The hospital is no longer looking backward.

It's operating in near real time.

This aligns perfectly with the philosophy we've been developing.

---

# SynBot Health Engineering Specification 008

# Reporting, Analytics & Operational Intelligence Engineering Specification (RAOIES)

**Version:** 1.0

**Project:** SynBot Health

**Engineering Specification:** SHES-008

**Architecture References**

* SHAS-009 — Reporting & Analytics Standard
* SHAS-010 — Dashboard & Operational Intelligence Standard
* SHAS-015 — Clinical Intelligence Standard
* SHES-002 — Workflow Engine
* SHES-007 — Event Bus & Messaging

**Status:** Engineering Specification

---

# 1. Purpose

The Reporting, Analytics & Operational Intelligence Platform transforms operational activity into actionable insights.

Rather than relying solely on transactional databases, SynBot Health continuously aggregates workflow events, clinical activities, financial transactions, and operational metrics into a governed analytics platform.

The objective is to provide real-time visibility for clinicians, operational teams, executives, and AI services.

---

# 2. Engineering Philosophy

Traditional HMS

```text id="trad001"
Database

↓

SQL Report

↓

Export Excel

↓

Management
```

---

SynBot Health

```text id="syn001"
Workflow

↓

Events

↓

Analytics Pipeline

↓

Metrics Engine

↓

Dashboards

↓

Alerts

↓

Executive Intelligence

↓

AI
```

Reports become a by-product.

Operational intelligence becomes the product.

---

# 3. Responsibilities

The Analytics Platform owns:

* KPI generation
* Dashboard metrics
* Operational reporting
* Executive reporting
* Clinical quality indicators
* Revenue analytics
* AI feature datasets
* Trend analysis
* Benchmark calculations

It does **not** own transactional workflows.

---

# 4. Engineering Architecture

```text id="arch001"
Operational Database

+

Event Store

↓

Analytics Pipeline

↓

Operational Data Store (ODS)

↓

Metrics Engine

↓

Dashboard Service

↓

Reporting Service

↓

AI Feature Store
```

This separates analytical workloads from transactional workloads.

---

# 5. Backend Modules

```text id="mod001"
/analytics/

metrics.py

dashboard.py

reporting.py

aggregation.py

scheduler.py

feature_store.py

warehouse.py

router.py
```

Each module performs a single analytical responsibility.

---

# 6. Analytics Layers

Layer 1

Operational Metrics

↓

Layer 2

Department KPIs

↓

Layer 3

Hospital KPIs

↓

Layer 4

Executive Intelligence

↓

Layer 5

AI Insights

Each layer builds upon the previous one.

---

# 7. Data Sources

Analytics consumes:

* Workflow Events
* Patient Encounters
* Clinical Notes
* Laboratory Results
* Radiology Reports
* Pharmacy Transactions
* Billing Transactions
* HMO Claims
* Audit Logs
* Notification Events

All analytics originate from governed operational data.

---

# 8. Operational Data Store (ODS)

The ODS provides optimized read models for reporting.

Characteristics:

* Near real-time synchronization
* Read-optimized schema
* Denormalized aggregates where appropriate
* Immutable event references
* Refresh monitoring

The ODS is not the source of truth; it is the analytical projection of operational data.

---

# 9. Metrics Engine

The Metrics Engine computes reusable indicators.

Examples:

* Average waiting time
* Consultation duration
* Laboratory turnaround time
* Radiology turnaround time
* Pharmacy dispensing time
* Admission occupancy
* Theatre utilization
* Revenue collected
* Outstanding claims
* Dialysis machine utilization

Metrics are defined once and reused across dashboards and reports.

---

# 10. Dashboard Framework

Every dashboard consists of reusable widgets.

```text id="dash001"
Dashboard

↓

Widget

↓

Metric

↓

Visualization

↓

Interaction
```

Widgets remain configurable and reusable.

---

# 11. Dashboard Types

Examples include:

Clinical Dashboard

Operational Dashboard

Department Dashboard

Executive Dashboard

Financial Dashboard

Quality Dashboard

AI Dashboard

Each dashboard targets a distinct audience.

---

# 12. Reporting Engine

Supports:

* Scheduled reports
* On-demand reports
* Parameterized reports
* Export (PDF, Excel, CSV)
* Email distribution
* Versioned report templates

Report generation should not affect operational system performance.

---

# 13. KPI Catalogue

Every KPI is governed.

Example metadata:

```json id="kpi001"
{
  "code": "",
  "name": "",
  "description": "",
  "formula": "",
  "owner": "",
  "refreshFrequency": "",
  "target": ""
}
```

KPIs are version-controlled and documented.

---

# 14. Alert Engine

Alerts trigger when metrics exceed configured thresholds.

Examples:

* OPD waiting time > target
* Laboratory backlog
* Theatre idle time
* Pharmacy stock-out risk
* High claim rejection rate
* Increased infection rate

Alerts generate events and notifications rather than remaining passive indicators.

---

# 15. Trend Analysis

Support analysis over:

* Hourly
* Daily
* Weekly
* Monthly
* Quarterly
* Annual

Trend calculations should support comparisons against historical baselines.

---

# 16. Executive Intelligence

Executive dashboards include:

* Hospital census
* Revenue performance
* Clinical throughput
* Patient satisfaction indicators
* Capacity utilization
* Staff productivity
* Financial health
* Operational bottlenecks

Executives should move from summary to detail without changing analytical context.

---

# 17. AI Feature Store

The platform prepares governed datasets for AI models.

Examples:

* Waiting time history
* Admission history
* Medication adherence
* Laboratory turnaround
* Bed occupancy
* Financial collections
* Workflow durations

Feature definitions remain versioned to ensure reproducibility.

---

# 18. API Endpoints

```http id="api001"
GET /analytics/dashboard/{type}

GET /analytics/metrics

GET /analytics/kpi/{code}

GET /analytics/report/{id}

POST /analytics/report/generate

GET /analytics/trends

GET /analytics/alerts
```

Analytics APIs expose read-only views optimized for reporting.

---

# 19. State Management

Frontend stores:

```text id="state001"
dashboardStore

metricsStore

reportStore

alertStore

trendStore

filterStore
```

Filters and time ranges should be shared across widgets where appropriate.

---

# 20. Performance Targets

Dashboard load

<2 seconds

Widget refresh

<500 ms

Report generation

<10 seconds (standard reports)

Metric calculation

<200 ms (cached)

ODS synchronization lag

<60 seconds

Performance goals should be reviewed as data volume grows.

---

# 21. Security

Analytics enforces:

* Role-based dashboard access
* KPI visibility rules
* Department-level filtering
* Patient data masking where required
* Export authorization
* Audit logging for report access

Sensitive operational information must be protected according to organizational policy.

---

# 22. Testing Strategy

### Unit

* KPI calculations
* Aggregation logic
* Widget rendering

### Integration

* ODS synchronization
* Report generation
* Dashboard filtering
* Alert creation

### Load

* Concurrent dashboard users
* Large report generation
* Metric refresh cycles

### Regression

* KPI consistency
* Historical trend accuracy
* Export validation

---

# 23. Acceptance Criteria

The Analytics Platform is complete when:

* Operational data is transformed into governed analytical datasets.
* Dashboards update from reusable metrics.
* Reports are generated without impacting transactional performance.
* KPIs remain centrally defined and version-controlled.
* Alerts respond automatically to threshold breaches.
* AI services consume standardized feature datasets.
* Executives, departments, and clinicians receive role-appropriate insights.

---

# 24. Developer Deliverables

## Backend

* Analytics Pipeline
* Operational Data Store synchronizer
* Metrics Engine
* Reporting Service
* Dashboard Service
* Alert Engine
* Feature Store

## Frontend

* Dashboard Framework
* Widget Library
* KPI Explorer
* Report Viewer
* Trend Explorer
* Alert Center

## QA

* KPI validation suite
* Dashboard performance testing
* Export verification
* Historical trend validation

## DevOps

* Scheduled aggregation jobs
* ODS monitoring
* Metrics monitoring
* Dashboard health checks
* Data freshness monitoring

---

# Annex A – FastAPI Implementation

```text id="annexA001"
app/
└── modules/
    └── analytics/
        ├── router.py
        ├── dashboard.py
        ├── metrics.py
        ├── reporting.py
        ├── aggregation.py
        ├── scheduler.py
        ├── feature_store.py
        ├── warehouse.py
        └── schemas.py
```

Aggregation jobs should remain independent from API request handling.

---

# Annex B – PostgreSQL Schema

Core tables:

* `analytics_metric`
* `analytics_kpi`
* `analytics_dashboard`
* `analytics_widget`
* `analytics_report`
* `analytics_report_run`
* `analytics_alert`
* `analytics_feature_definition`
* `analytics_snapshot`

Recommended indexes:

* `metric_code`
* `dashboard_type`
* `report_template`
* `snapshot_timestamp`
* `department_id`

The ODS may also include materialized views for frequently accessed aggregations.

---

# Annex C – React Implementation

```text id="annexC001"
AnalyticsShell
│
├── DashboardGrid
├── KPIWidget
├── TrendChart
├── AlertPanel
├── ReportViewer
├── FilterToolbar
├── ExportDialog
└── ExecutiveSummary
```

Widgets should support responsive layouts and configurable refresh intervals.

---

# Annex D – End-to-End Sequence Flow

```text id="annexD001"
Consultation Completed

↓

Workflow Event Published

↓

Event Bus

↓

Analytics Pipeline

↓

Operational Data Store Updated

↓

Metrics Recalculated

↓

Dashboard Widget Refreshed

↓

Threshold Evaluated

↓

Alert Generated (if applicable)

↓

Executive Dashboard Updated

↓

AI Feature Store Refreshed
```

This flow demonstrates that analytics are not an afterthought—they are continuously derived from operational activity.

---

# Architect's Note

I think **SHES-008** closes the loop we've been building since the first engineering specification.

The sequence now looks like this:

1. **SHES-001** — Users have a consistent workspace.
2. **SHES-002** — The Workflow Engine orchestrates care.
3. **SHES-003** — Clinicians work from a unified clinical workspace.
4. **SHES-004** — Structured clinical data is captured intelligently.
5. **SHES-005** — Governed master data standardizes every interaction.
6. **SHES-006** — Departments inherit a common engineering framework.
7. **SHES-007** — Events connect every service asynchronously.
8. **SHES-008** — Operational activity becomes measurable intelligence.

These eight specifications form the **Platform Engineering Core** of SynBot Health.

From here, the engineering work becomes increasingly domain-focused: security, interoperability, AI orchestration, integrations, deployment, and implementation of the individual departmental services. The core foundation is now strong enough that every future capability can plug into a consistent architectural framework rather than introducing new patterns.
