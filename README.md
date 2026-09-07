# Retail SOP

A Frappe/ERPNext app that powers SOP execution and compliance tracking for
multi-outlet food courts — pre-opening, service-round, and closing
checklists, deviation/escalation tracking, and compliance reporting.

The app is a **backend only**: it defines doctypes, validation rules, a
daily scheduler, and a whitelisted REST API. All day-to-day data entry
happens through a separate frontend (built in Lovable.dev) that talks to
this app exclusively through the API in [`retail_sop/api.py`](retail_sop/api.py).
The Frappe Desk UI is available for admin configuration (managing
templates, outlets, roles) but is not customized beyond standard
doctype forms.

---

## 1. Project overview

**Problem it solves**: a food court operator runs the same SOP checklist
(pre-opening safety/hygiene checks, mid-shift service rounds, closing
checks) across many outlets, every day, executed by supervisors and
reviewed by managers. Failures need to escalate automatically as tracked
deviations, and management needs compliance trends and vendor scorecards
without digging through paper checklists.

**How this app solves it**:

- A **Checklist Template** defines the reusable list of checks for a given
  shift type (Pre-Opening / Service Round / Closing).
- Every day, a scheduled job stamps out one **Shift Checklist** (Draft) per
  active template, with all check rows pre-populated from the template.
- Supervisors fill in each row's status (OK / Not OK / NA) via the frontend
  app, which calls the whitelisted API — never the Frappe Desk directly.
- On submit, the checklist is validated server-side (mandatory checks
  answered, photos attached where required, numeric readings within
  range), and any failed check configured to escalate automatically spins
  off a **Checklist Deviation** record.
- A submitted checklist moves through a lightweight approval **workflow**
  (Draft → Submitted → Verified) so a manager signs off on the shift.
- Deviations are tracked to resolution (Open → In Progress → Pending
  Vendor → Closed), with automatic email alerts for Critical-severity
  issues.
- A single reporting API (`get_dashboard_data`) feeds the frontend's
  compliance dashboards: compliance trend, deviations by outlet/category,
  open vs closed, vendor scorecard, and repeat-failure detection.

---

## 2. Tech details

| | |
|---|---|
| Framework | [Frappe](https://frappeframework.com/) (installed as an app on an existing ERPNext bench) |
| App name / module | `retail_sop` / **Retail SOP** |
| Language | Python 3.10+ (server), vanilla JS (one desk client script) |
| Storage | MariaDB, via the standard Frappe ORM (`frappe.get_doc`, `frappe.get_all`, parameterized `frappe.db.sql` for reporting) |
| Auth (current) | Frappe token auth — `Authorization: token <api_key>:<api_secret>` — checked once via a single `_check_auth()` chokepoint in `api.py` so the strategy is easy to swap later |
| Dependencies | `frappe`, `erpnext` (for the `Employee` and `Customer` link targets) |
| Frontend | Built separately in Lovable.dev; integrates only via the whitelisted REST API |

### App layout

```
retail_sop/
├── hooks.py                 # app config: scheduler_events, fixtures, doctype_js
├── tasks.py                 # daily scheduler job
├── api.py                   # whitelisted REST API (the frontend's only entry point)
├── public/js/shift_checklist.js   # desk-only client script
├── fixtures/                # Role, Workflow, Workflow State/Action, Notification
├── patches/v0_0/             # seed data patch (demo checklist template)
└── retail_sop/
    ├── doctype/
    │   ├── outlet/
    │   ├── checklist_template/            (+ checklist_template_item, child table)
    │   ├── shift_checklist/               (+ shift_checklist_item, child table)
    │   └── checklist_deviation/
    └── workspace/retail_sop/retail_sop.json   # home screen menu (see §11)
```

---

## 3. Doctypes

### Outlet (master)
Simple list of physical outlets/areas, e.g. individual food stalls plus a
shared `Common Area` entry (seeded by the demo patch). Used as the `Link`
target for `Checklist Template.location`, `Shift Checklist.location`, and
`Checklist Deviation.outlet` — one configurable list instead of a
hardcoded Select duplicated across doctypes.

### Checklist Template (master) → Checklist Template Item (child)
Defines a reusable checklist for a shift type. Each item row configures:
category, input type (Tick / Numeric / Text / Photo), a standard/reference
value, numeric min/max thresholds, and flags — `is_mandatory`,
`requires_photo`, `escalate_on_fail`, `vendor_specific` — plus who to
escalate to (`escalate_to_type`: User or Role, with a matching `Dynamic
Link` field).

### Shift Checklist (submittable) → Shift Checklist Item (child)
One execution instance of a template for a given date/shift. Naming
series `EXO-CHK-.YYYY.-.####`. Each item row is linked back to its
template row via a hidden `template_item` field, and `sr_no`,
`check_description`, `category`, `standard` are populated via Frappe's
`fetch_from` mechanism — set once when the row is created, read-only
after. `compliance_score`, `total_checks`, and `failed_checks` are
computed server-side on every save (see §5).

### Checklist Deviation (submittable)
An issue raised either automatically (by a failed, escalate-on-fail
check) or manually via the API. Naming series `EXO-DEV-.#####`. Tracks
severity, resolution status, and closure (`closed_by`/`closed_on`).

---

## 4. Roles & permissions

Three roles, on top of the standard `System Manager`:

| Role | Checklist Template | Shift Checklist | Checklist Deviation |
|---|---|---|---|
| **System Manager** | full CRUD | full CRUD + submit/cancel/amend | full CRUD + submit/cancel/amend |
| **Food Court Supervisor** | read-only | create, read, write, **submit** | create, read, write, submit |
| **Food Court Manager** | read + report | read, write (to Verify) + report | full CRUD + submit/cancel/amend |

`Food Court Supervisor` and `Food Court Manager` are shipped as a
[Role fixture](retail_sop/fixtures/role.json) so they exist right after
install — no manual setup step.

---

## 5. Server-side logic

### Daily scheduler — `retail_sop.tasks.create_daily_shift_checklists`
Registered in `hooks.py` under `scheduler_events.daily`. For every active
`Checklist Template`, creates one `Shift Checklist` in Draft status dated
today, with one item row per template row (skips if a checklist for that
template/date already exists, so re-running the scheduler is safe).

### `ShiftChecklist.validate()` — single source of truth
Runs on every save, including submit (Frappe sets `docstatus=1` *before*
calling `validate()` on submit, so the same method can gate submit-only
rules with `if self.docstatus == 1`). Responsibilities, in order:

1. **Date immutability** — blocks changing `date` after the first save
   (prevents back-dating), and blocks creating a new checklist dated in
   the past.
2. **Workflow transition guard** — a code-level backstop (see §6) that
   re-checks the acting user's role against the declared workflow.
3. **Numeric range check** — for `input_type = Numeric` rows, compares
   `reading` against the template item's `min_value`/`max_value` and
   auto-flips `status` to `Not OK` if out of range (0/0 is treated as "no
   range configured").
4. **Compliance summary** — recomputes `total_checks`, `failed_checks`,
   and `compliance_score` (`OK ÷ (OK + Not OK) × 100`; `NA` rows are
   excluded from the denominator).
5. **Submit-time blocking rules** (only when `docstatus == 1`) — every
   mandatory row must have a status; every `Not OK` row on a
   `requires_photo` item must have an attachment. Violations raise
   `ShiftChecklistValidationError`, a `ValidationError` subclass carrying
   a structured `rows: [{row, idx, sr_no, check_description, message}]`
   list.

### `ShiftChecklist.on_submit()`
For every row left `Not OK` whose template item has `escalate_on_fail`
checked, auto-creates a `Checklist Deviation` (outlet, category, and a
default severity of **Medium** — flagged as an assumption, not specified
in the original brief) linked back to the checklist and the escalation
target from the template item.

### `ChecklistDeviation.after_insert()`
If `severity == "Critical"`, emails everyone with the `Food Court
Manager` role. This runs on **creation** (insert), not submit — a
critical issue shouldn't wait for someone to formally submit the record
before management is alerted. Primary delivery is the declarative
[Notification fixture](retail_sop/fixtures/notification.json)
(Settings → Notification, Email channel); `notify_food_court_managers()`
in `checklist_deviation.py` is a direct `frappe.sendmail` backstop so the
alert still fires even if that fixture doesn't import cleanly on a given
site/version.

---

## 6. Workflow

`Shift Checklist` carries a `workflow_state` field driving:

```
Draft ──(Submit, role: Food Court Supervisor)──▶ Submitted ──(Verify, role: Food Court Manager)──▶ Verified
```

- **Draft → Submitted** is a real Frappe submit action (`docstatus` 0 → 1).
- **Submitted → Verified** only changes `workflow_state` (`docstatus`
  stays 1); the field is `allow_on_submit` so a manager can make that one
  edit on an already-submitted document.
- The whole thing is configured declaratively as a
  [Workflow fixture](retail_sop/fixtures/workflow.json) (plus its
  [Workflow State](retail_sop/fixtures/workflow_state.json) and
  [Workflow Action Master](retail_sop/fixtures/workflow_action_master.json)
  fixtures), so it's fully editable from Desk → Workflow after install.
- `ShiftChecklist.enforce_workflow_state_transition()` (in `validate()`)
  is a code-level backstop: it independently re-checks that any
  `workflow_state` change matches a known transition and that the acting
  user holds the required role, so the rule holds even if the Workflow
  record is edited or misconfigured on a given site.
- Standard Frappe submittable-doctype behavior already blocks editing any
  other field once `docstatus = 1`, which covers "prevent edits outside
  the workflow" for free.

---

## 7. Client script (Desk fallback only)

[`public/js/shift_checklist.js`](retail_sop/public/js/shift_checklist.js)
watches the `status` field on `Shift Checklist Item` rows and stamps
`checked_at` (now) / `checked_by` (session user) client-side. This
**only matters if someone edits a Shift Checklist directly through the
Frappe Desk form** — it is not part of the frontend's data path. Both
fields are already `read_only` at the schema level, so they're
effectively immutable to direct user edits with or without this script;
it exists purely so a Desk user sees them populate live.

The real data-entry path — the Lovable frontend calling `update_check_item`
in `api.py` — does its own independent server-side stamping (see §8) and
does not rely on this script at all.

The same file also covers a second Desk-only gap: `sr_no`,
`check_description`, `category`, and `standard` on `Shift Checklist Item`
are read-only `fetch_from` fields sourced from a hidden `template_item`
link, which the daily scheduler sets on every row it creates. A Shift
Checklist created manually in Desk starts with zero rows and no way to
set that hidden link itself, so those fields would otherwise be
permanently unreachable. Selecting a `Checklist Template` on the parent
form (or clicking the **Get Items From Template** button it adds) calls
the whitelisted `get_template_items` function in `shift_checklist.py`
and populates the items table client-side — no save required first.

---

## 8. Whitelisted API (`retail_sop/api.py`)

Every method is `@frappe.whitelist()` and goes through `_check_auth()`.
Responses are plain dicts/lists — no Frappe internals leak through.

| Method | Purpose |
|---|---|
| `get_todays_checklists(supervisor=None)` | Today's Shift Checklists, optionally filtered by supervisor |
| `get_checklist_detail(name)` | Full checklist with items, each row carrying its template context (standard, thresholds, mandatory/photo flags) |
| `update_check_item(checklist, row_name, status=None, reading=None, remarks=None)` | Updates one row; stamps `checked_at`/`checked_by` server-side; returns live `compliance_score`/`failed_checks` |
| `submit_checklist(name)` | Calls `doc.submit()`; on `ShiftChecklistValidationError`, reshapes the exception's own structured data into `{success: false, message, blocking_rows: [{row, message, ...}]}` — it does **not** run a second validation pass, `validate()` is the only place that logic lives |
| `create_deviation(...)` | Manual/ad-hoc deviation raise |
| `update_deviation_status(name, resolution_status, closed_by=None)` | Moves a deviation through resolution; stamps `closed_by`/`closed_on` on Closed |
| `get_deviations(outlet=None, resolution_status=None)` | Feed for a Kanban-style deviation board |
| `get_dashboard_data(report_type, from_date, to_date, outlet=None)` | Single reporting entry point, dispatching to one of 5 report types (below) |

### Dashboard report types

Proposed shapes — flagged as an assumption pending confirmation of the
frontend's exact needs; each is documented with its return shape as a
docstring on the corresponding `_report_*` helper in `api.py`.

| `report_type` | Returns |
|---|---|
| `compliance_trend` | Average compliance % per outlet per calendar month |
| `deviations_by_outlet_category` | Deviation counts grouped by outlet & category |
| `open_vs_closed` | Open vs closed deviation counts, plus a full breakdown by `resolution_status` |
| `vendor_scorecard` | Per-vendor total/failed checks and compliance % |
| `repeat_failures` | Checks failing more than 3×/month at the same outlet |

---

## 9. Installation

```bash
bench get-app retail_sop /path/to/retail_sop
bench --site your-site install-app retail_sop
bench --site your-site migrate   # applies the seed-data patch
```

After install, `bench --site your-site backup` then verify:
- Roles **Food Court Supervisor** / **Food Court Manager** exist (Users
  and Permissions → Role).
- Workflow **Shift Checklist Workflow** exists and is active (Settings →
  Workflow).
- A demo template **Pre-Opening Demo** exists (Retail SOP → Checklist
  Template) with a placeholder 12-check list — replace with the real
  reference checklist.
- Generate API keys for supervisor/manager users (User → API Access) for
  the frontend to authenticate with.

---

## 10. Known assumptions / open items

These were called out during development rather than guessed silently —
worth confirming against real requirements:

- **Outlet as a Link doctype** (not a hardcoded Select) for
  `location`/`outlet` fields, seeded with one `Common Area` record.
- **Default severity "Medium"** for auto-raised deviations.
- **Compliance score** excludes `NA` rows from the denominator.
- **Deviation notification fires on insert**, not on submit.
- **Dashboard report shapes** are a proposal, not a confirmed contract.
- **Workflow / Notification fixture schemas** were hand-written from
  framework knowledge without a live bench to verify field names against
  — double-check after the first `bench migrate` on your target version;
  the code-level backstops (§6, §5) keep the actual business rules
  enforced even if a fixture field needs a small correction.
- The 12-item demo checklist in the seed patch is a **placeholder** —
  swap in the real reference list.
- **Workspace content-block schema** (§11) was hand-written from
  framework knowledge without a live bench to verify against — same
  caveat as the Workflow/Notification fixtures, but lower risk: a
  malformed `content` block degrades to a blank/plain page rather than
  breaking install, and the underlying `links`/`shortcuts` data is
  still there to rebuild from inside the block editor if needed.

---

## 11. Home screen (Workspace)

A **Retail SOP** entry appears in the Desk sidebar/home screen
automatically after install — no manual setup. It's defined at
[`retail_sop/retail_sop/workspace/retail_sop/retail_sop.json`](retail_sop/retail_sop/workspace/retail_sop/retail_sop.json),
which uses Frappe's standard module-sync mechanism (the same one that
syncs doctypes, reports, and pages): any `<module>/workspace/<name>/<name>.json`
file is picked up automatically by `bench migrate` — it is **not** part
of the generic `fixtures` list in `hooks.py`.

It's a public workspace (visible to anyone who can open at least one of
the linked doctypes) with:
- Four **shortcuts** at the top: Shift Checklist, Checklist Deviation,
  Checklist Template, Outlet.
- Two **card** groupings below: "Operations" (Shift Checklist, Checklist
  Deviation) and "Configuration" (Checklist Template, Outlet).

If the workspace ever renders blank or oddly laid out on a given Frappe
version (content-block schemas have shifted across versions — see the
caveat in §10), the underlying `links`/`shortcuts` data that feeds it is
still correct; open **Retail SOP → Edit** in Desk and rebuild the visual
layout from those — no data re-entry needed, just a 2-minute drag/drop.

---

## License

MIT
