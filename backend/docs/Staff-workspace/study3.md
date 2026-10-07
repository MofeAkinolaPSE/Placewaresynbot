Exactly. That's one of the main ideas behind the **Operational Task Engine**.

For example:

```text
Stock Item
   │
   ├── Expiry date approaching
   │
   ▼
Inventory Event
   │
   ▼
Rule Engine
   │
   ├── Which company?
   ├── Which facility?
   ├── Which department?
   ├── Which stock/item?
   └── Who is responsible?
   │
   ▼
Create Operational Task
   │
   ├── Inventory Officer
   ├── Store/Pharmacy Team
   └── Supervisor (if required)
   │
   ▼
Staff Workspace
   │
   ├── My Day
   ├── Inbox
   └── Needs Attention
```

So instead of someone having to remember to check expiry dates, **Synbot detects the condition and creates the work automatically**.

And we can make the rule configurable. For example:

| Condition         | Action                    |
| ----------------- | ------------------------- |
| 90 days to expiry | Inform inventory team     |
| 60 days           | Create review task        |
| 30 days           | High-priority action task |
| 7 days            | Escalate to supervisor    |
| Already expired   | Critical exception        |

The important part is that **"inform" and "create a task" don't have to be the same thing**.

For instance:

> **90 days:** notification only
> **60 days:** inventory review task
> **30 days:** action required + supervisor notification
> **Expired:** escalation + operational exception

And because the task retains the actual stock item's `entity_type` and `entity_id`, the employee can click the task and go directly to the affected batch/item.

This is exactly where the Staff Workspace starts becoming powerful: **employees don't just check dashboards; Synbot tells them what requires human action based on what is happening in the business.**
