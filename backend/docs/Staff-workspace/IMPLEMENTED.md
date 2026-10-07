# Staff Workspace: what was built for Placeware (Sep 2026)

This note records what the research in this folder became in the Placeware/ACE app. The research describes a generic, multi-company Synbot engine. For this client we built the parts that apply, on the app's existing tables. We did not create a parallel `staff_*` identity model.

## Pages

| Page | Route | Who |
|---|---|---|
| **My Workspace** (replaces Staff Dashboard, Time Tracker and Collaboration; their old links redirect here) | `#/workspace` | every signed-in user |
| **HR** (rewritten) | `#/hr` | admin and HR act; management reads |

**My Workspace has six tabs:**
- **My Day:** clock, today's timeline, needs attention, operational items for my role, waiting on others, my day so far.
- **My Work:** tasks, reminders and notes, filtered by today, upcoming, no date, waiting, done, or given to others.
- **Inbox:** notifications and requests.
- **Messages:** one-to-one and whole-team chat.
- **Team:** presence, workload, and message / ask / give task.
- **Progress:** completed, on time, requests answered, hours, work journal, and my timesheet.

The work clock and an inbox bell are also in the top bar on every page.

**HR has three tabs:**
- **Overview:** online now, on the clock now, and hours per person this week, with saved and running time kept separate and summed in the headline. Also hours by department, the last 8 weeks, and clocks left running.
- **Directory:** everyone on User Access plus HR-only records, each with an editable profile.
- **Timesheets:** approve, reject or adjust with a reason; add hours for someone; export to CSV.

## Mapping from the research to the implementation

| Research | Implemented as |
|---|---|
| staff / staff_profiles | `placeware_users` (the login) ↔ `placeware_staff` (the HR profile), linked by `user_id`. The profile is created when an account is made on User Access, or on first use. |
| staff_tasks + checklist / comments / activity | `placeware_tasks`, extended with kind, entity_type/entity_id, link, checklist, waiting_on and completed_by; plus `staff_task_activity` |
| Task state machine | to do → in progress ⇄ waiting → done (reopen / cancel). The research's inbox / accepted / verified / closed states were left out; this client does not assign work formally. |
| staff_requests + messages | `staff_requests`, `staff_request_messages`. There are info and work requests: a work request creates a task for the recipient, and completing that task answers the request. |
| staff_notifications (four levels) | `staff_notifications` (critical / action / info / social) |
| staff_time_sessions / break_sessions | `staff_time_sessions` (breaks are summed on the session). Clock-out writes `placeware_timesheets` (source `clock`, status `submitted`). |
| staff_work_events (journal) | `staff_work_events` |
| staff_preferences | `staff_preferences` |
| Direct messages / channels | the existing `threads` tables (`dm:<a>:<b>` and `team:all`) |
| Operational Task Engine | Rules in `services/staff_workspace.py` (`RULES`) read live records: stock orders to place, deliveries due or overdue, quality items due (batch release, recalls, audits, maintenance, deviations, CAPA), expired stock still sellable, supplier payments due, CRM follow-ups, cold proposals, timesheets to approve, and clocks left running. Nothing is created until someone takes an item. A taken task **closes itself** once the record is dealt with in its module. |
| Company switcher / multi-company RBAC | Not built. Placeware is one company. Scope comes from the token, never from the request. |
| Real-time | the `workspace_updates` websocket channel, which carries only a refresh signal and never content |
| AI panel / command bar | Not built yet. The structured workspace comes first, as the research advises. |
| Natural task creation | `services/task_language.py`, exposed as `POST /workspace/parse` (preview) and `/workspace/quick`. A quick-add bar sits on My Day and My Work. It is deterministic, with no AI call. It understands:<ul><li>remind me / note: / ask X to / @name / for X</li><li>priority words: urgent, important, low priority</li><li>dates: today, tomorrow, Friday, 12 Oct, 15/10, in 2 hours, eod, end of week or month</li><li>times: 10am, 15:00, morning</li><li>repeats: every Monday, weekdays, 21st of every month, end of every month, every 2 weeks, "until"</li><li>a department</li></ul>It shows what it understood before saving. |
| Recurring tasks (not in v1 of the research) | `placeware_tasks.recurrence`, `recurrence_until` and `series_id` (migration 125); `workspace_automation.next_after` / `schedule_next`. Finishing or skipping one creates the next, from today onward, so missed ones don't pile up; the checklist is reset. There is a "Stop repeating" option. |
| Escalation (study4: "Business Event → Decision → Human Action → Escalation") | `staff_escalation_policy`, one chain per priority plus one for requests, editable under Customise → Escalation rules (admin, management, HR). `run_escalations()` runs every 5 minutes; each step is claimed with a conditional update, so it fires once even with several workers. The chain goes: the person doing it → whoever gave it → management (critical). Rules:<ul><li>Notes never escalate; reminders only remind their owner.</li><li>A task entered after its due time starts its chain when it was entered.</li><li>Moving the due date restarts the chain.</li></ul> |

## Bug fixed
Clocking out failed with "timesheet could not be recorded". The timer ran in the browser and posted the **login id** as `staff_id`, and `placeware_timesheets.staff_id` is a foreign key to `placeware_staff`, so the insert failed for every account without an HR record (6 of 8 at the time). The endpoint also rejected sales, finance and QA users outright.

Now:
- the clock runs on the server;
- the profile is linked or created automatically;
- anyone can record their own hours;
- HR, admin and management can record anyone's.

## Code
- **Migration:** `backend/migrations/124_staff_workspace.sql`
- **Services:** `backend/src/services/staff_workspace.py` and `hr_hub.py`
- **Routers:** `backend/src/routers/staff_workspace.py` (prefix `/workspace`) and `hr_hub.py` (prefix `/hr`)
- **Frontend:** `SynbotUI/client/pages/StaffWorkspace.tsx`, `pages/HR.tsx`, `components/staff/ws-kit.tsx`, `ws-panels.tsx` and `components/hr/hr-panels.tsx`
