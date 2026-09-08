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
├── hooks.py                 # app config: scheduler_events, fixtures, doctype_js, before_request
├── tasks.py                 # daily scheduler job
├── api.py                   # whitelisted REST API (the frontend's only entry point)
├── auth/                    # JWT bearer-token auth (see §12) - login/refresh/logout/me,
│   ├── api.py                #   JWT signing, the before_request bypass middleware
│   ├── jwt_utils.py
│   ├── middleware.py
│   └── utils.py
├── public/js/shift_checklist.js   # desk-only client script
├── fixtures/                # Role, Workflow, Workflow State/Action, Notification
├── patches/v0_0/             # seed data patch (demo checklist template)
└── retail_sop/
    ├── doctype/
    │   ├── outlet/
    │   ├── checklist_template/            (+ checklist_template_item, child table)
    │   ├── shift_checklist/               (+ shift_checklist_item, child table)
    │   ├── checklist_deviation/
    │   └── auth_session/                  # one row per logged-in device/session (see §12)
    └── workspace/retail_sop/retail_sop.json   # home screen menu (see §11)
```

---

## 3. Doctypes

### Outlet (master)
Simple list of physical outlets/areas, e.g. individual food stalls plus a
shared `Common Area` entry (seeded by the demo patch). Used as the `Link`
target for `Checklist Template.location`, `Shift Checklist.location`, and
`Checklist Deviation.outlet` — one configurable list instead of a
hardcoded Select duplicated across doctypes. `store_operator` (Link →
User, optional) assigns the one Store Operator account that can see this
outlet's read-only hygiene/rating summary (§8, §12) — one operator per
outlet.

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

Four roles, on top of the standard `System Manager`:

| Role | Checklist Template | Shift Checklist | Checklist Deviation |
|---|---|---|---|
| **System Manager** | full CRUD | full CRUD + submit/cancel/amend | full CRUD + submit/cancel/amend |
| **Food Court Supervisor** | read-only | create, read, write, **submit** | create, read, write, submit |
| **Food Court Manager** | read + report | read, write (to Verify) + report | full CRUD + submit/cancel/amend |
| **Store Operator** | none | none | none |

`Store Operator` deliberately holds **no doctype-level permission** on
any of these — it's not a smaller version of Supervisor/Manager, it's a
narrow, code-scoped view onto one outlet's data. It can authenticate
(§12) and call exactly one endpoint,
[`get_my_store_summary()`](#8-whitelisted-api-retail_sopapipy), which
looks up the single `Outlet` where `store_operator` = that user and
returns only that outlet's Hygiene-category check results and an
overall rating — nothing else, and no other outlet's data. It also has
`desk_access: 0` (unlike the other two roles), since it's meant purely
for this one read-only view, not Desk use.

One consequence worth knowing: because Store Operator has no read
permission on `Shift Checklist`, calling one of the broader endpoints in
§8 (`get_today_checklists`, `get_deviations`, etc.) as a Store Operator
doesn't error — Frappe's permission-filtered `get_all` just silently
returns an empty list. No data leaks either way, but it's a quiet empty
result rather than an explicit rejection; worth keeping in mind if this
ever needs to change to a hard error instead.

`Food Court Supervisor`, `Food Court Manager`, and `Store Operator` are
all shipped as a [Role fixture](retail_sop/fixtures/role.json) so they
exist right after install — no manual setup step (assigning a Store
Operator to a specific `Outlet.store_operator` is still a manual step,
done per-outlet in Desk).

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

This API is written to match a specific, already-built frontend —
[pixel-perfect](https://github.com/Vijay-micronxt/pixel-perfect), a
Lovable-generated app whose `src/services/sopService.ts` and
`src/services/types.ts` document the exact contract every screen is
coded against (currently backed by in-memory mock data there; wiring it
up to this API means swapping each function body in `sopService.ts` for
a `fetch()`/`frappe.call()` to the matching method below — the frontend's
own function names, parameters, and return shapes were the spec for
this rewrite, not the other way around).

| Frontend (`sopService.ts`) | Backend (`api.py`) | Notes |
|---|---|---|
| `listOutlets()` | `list_outlets()` | Active `Outlet` records |
| `listCategories()` | `list_categories()` | Pulled live from the `category` Select's options — single source of truth |
| `getTodayChecklists()` | `get_today_checklists()` | Full checklists (with items), not a summary list |
| `getChecklist(name)` | `get_checklist(name)` | `None` if not found |
| `getHistory(from, to)` | `get_history(from_date=None, to_date=None)` | Submitted checklists (any workflow state) in range |
| `getVerificationQueue()` | `get_verification_queue()` | Submitted + not-yet-Verified (covers Escalated too) |
| `getDeviations(outlet)` | `get_deviations(outlet=None)` | `"All"`/blank outlet means no filter |
| `getDashboardData()` | `get_dashboard_data()` | One call, all five sections — see below |
| `saveChecklistRow(name, sr_no, update)` | `save_checklist_row(checklist_name, sr_no, status=None, reading=None, remarks=None, attachment=None)` | Rows are identified by **`sr_no`**, not the child-row name; returns the **full** updated checklist |
| `submitChecklist(name)` | `submit_checklist(name)` | `{success, errors?: [{row, message}]}`, `row` is `str(sr_no)` — reshapes `ShiftChecklistValidationError`, no second validation pass |
| `verifyChecklist(name)` | `verify_checklist(name)` | New — the manager verify step happens via API now, not only via the Desk workflow button |
| `createDeviation(input)` | `create_deviation(outlet, category, severity, issue, action_taken, photo=None)` | Critical severity auto-sets `escalated_to = "Food Court Manager"` |
| `updateDeviationStatus(name, status)` | `update_deviation_status(name, resolution_status)` | Clears `closed_by`/`closed_on` when moved off Closed |

### `get_my_store_summary()` — Store Operator only

Not part of the pixel-perfect frontend contract above (no
`sopService.ts` equivalent yet) — a separate, narrower endpoint for the
`Store Operator` role (§4). Takes no arguments; looks up the single
`Outlet` where `store_operator` = the calling user and returns:

```json
{
  "outlet": "Spice Route",
  "rating": 91.5,
  "hygiene_checks": [
    {"date": "2026-09-05", "check_description": "...", "status": "OK", "remarks": null}
  ]
}
```

`rating` is the average `compliance_score` across that outlet's last 30
submitted Shift Checklists (not a fixed date window — flagged as an
assumption, adjust in `api.py` if a different definition of "rating" is
wanted). `hygiene_checks` is every `Hygiene`-category row from those same
checklists. Throws `PermissionError` if the calling user isn't set as
any outlet's `store_operator`.

A few deliberate departures from the app's original design, made to
match this frontend's actual contract:
- The doctype's own `status` field (Draft/In Progress/Completed/
  Escalated) is **not** what the API reports. `get_today_checklists`
  etc. compute a `status` string from `docstatus` + `workflow_state` +
  whether any row has been touched, matching the frontend's
  `ChecklistStatus` union (`Draft`/`In Progress`/`Submitted`/`Verified`/
  `Escalated`) exactly.
- `ShiftChecklist._compute_blocking_rows()` (in `shift_checklist.py`)
  now also blocks submit on a mandatory row that has a status but is
  incomplete for its input type (Numeric with no `reading`, Text with
  no `remarks`, Photo with no `attachment`) — mirroring the frontend's
  own `isRowComplete` check. This is new versus the original brief's two
  rules (blank mandatory status; missing photo on a Not OK) and was
  added so `submit_checklist`'s `errors` actually behave the way the
  frontend expects; it's still the single source of truth, just a
  broader one.
- `checked_at`/deviation `time` are formatted down to `HH:MM` (matching
  the frontend's display convention) rather than returned as full
  Frappe datetime strings.

### Dashboard data (`get_dashboard_data()`)

One call, no parameters — a departure from the app's original
per-report-type design, because that's what the frontend's contract
calls for. Returns:

| Key | Shape | Notes |
|---|---|---|
| `complianceTrend` | `[{month, outlet, compliance}]` | Last 6 months, submitted checklists only — window not configurable |
| `deviationsByOutlet` | `[{outlet, <category>: count, ...}]` | Wide/pivoted, one key per **real** category (`Common Area`/`Hygiene`/`Vendor Compliance`/`Revenue`/`Safety`) |
| `vendorScorecard` | `[{outlet, compliance, deviations}]` | Despite the name, this is outlet-level — matches how `dashboards.tsx` actually renders it ("Outlet scorecard") |
| `repeatFailures` | `[{check_description, outlet, fail_count}]` | All-time count per check+outlet, `> 3` — the original brief's per-month window doesn't fit this flatter shape |
| `escalations` | `{open, closed}` | Deviation counts by resolution status |

**Frontend follow-up needed**: `dashboards.tsx`'s bar chart currently
hardcodes `<Bar dataKey="Hygiene">`, `"Temperature"`, `"Safety"`,
`"Documentation"` — placeholder category names from the mock data that
don't match the doctype's real ones. It needs a small change to render
bars dynamically from whatever keys `deviationsByOutlet` actually
carries (or to hardcode the real 5 category names instead).

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
- Add JWT signing keys (and, if the frontend is a different origin,
  `allow_cors`) to `site_config.json` — **the frontend cannot log in
  until this is done**. See §12 "Setup" for the exact commands, and
  "Troubleshooting" there if login fails after this step.

---

## 10. Known assumptions / open items

These were called out during development rather than guessed silently —
worth confirming against real requirements:

- **Outlet as a Link doctype** (not a hardcoded Select) for
  `location`/`outlet` fields, seeded with one `Common Area` record.
- **Default severity "Medium"** for auto-raised deviations.
- **Compliance score** excludes `NA` rows from the denominator.
- **Deviation notification fires on insert**, not on submit.
- **Dashboard reporting windows** (last 6 months for the compliance
  trend, all-time for everything else) are a pick, not a confirmed
  spec — `get_dashboard_data()` takes no parameters because that's the
  frontend's contract, so there's nowhere to pass a date range in from.
- **Outlet-level "vendor" scorecard**: `vendorScorecard` groups by
  outlet, not the `vendor` (Customer) field on Shift Checklist Item —
  matches the frontend's actual "Outlet scorecard" card, but means the
  per-vendor compliance view from the original brief doesn't have an
  endpoint of its own yet.
- **Workflow / Notification fixture schemas** were hand-written from
  framework knowledge without a live bench to verify field names against
  — double-check after the first `bench migrate` on your target version;
  the code-level backstops (§6, §5) keep the actual business rules
  enforced even if a fixture field needs a small correction.
- The 12-item demo checklist in the seed patch is a **placeholder** —
  swap in the real reference list.
- **JWT `ALLOWED_ROLES` gate** (`auth/api.py`) is currently Food Court
  Supervisor + Food Court Manager + Store Operator + System Manager —
  adjust if other roles should be able to log in through this API. Being
  in this set only grants the ability to authenticate; it doesn't by
  itself grant access to any particular endpoint (see the Store Operator
  row in §4 — it's in `ALLOWED_ROLES` but has no doctype permissions).
- **Refresh token sliding expiration**: each successful `refresh_token`
  call resets `expires_at` to a fresh 30-day window rather than counting
  down from original login — a device in regular use effectively never
  needs to re-enter credentials. Flagging in case a hard expiration from
  login time is wanted instead.
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

## 12. Authentication (JWT bearer tokens)

The app-facing API (§8) authenticates via a self-contained JWT
bearer-token flow, not Frappe's cookie-session login (`/api/method/login`,
`sid` cookie, CSRF tokens). Built for an API-driven client (the
pixel-perfect SPA, or a mobile client) rather than a browser holding a
Frappe session cookie.

### Token model

Two token types, deliberately different:

| | `access_token` | `refresh_token` |
|---|---|---|
| Format | JWT (HS256) | Opaque random string (`secrets.token_urlsafe(48)`) |
| Lifetime | 40 min default (`retail_sop_access_token_ttl_seconds`) | 30 days default (`retail_sop_refresh_token_ttl_days`), sliding — resets on each use |
| Validated by | Signature + expiry check, no DB read — plus **one** DB read per request to check it hasn't been revoked | A DB lookup by hash; there's nothing to "validate" client-side |
| Stored server-side | Not stored at all (stateless) | Only its **sha256 hash**, in `Auth Session.refresh_token_hash` — the raw value is returned to the client once and never persisted |

### `Auth Session` doctype

One row per logged-in device/session:
[`retail_sop/retail_sop/doctype/auth_session/`](retail_sop/retail_sop/doctype/auth_session/).
`user`, `device_id`, `device_name`, `issued_at`, `expires_at`,
`revoked_at`, `refresh_token_hash` (unique), `prev_refresh_token_hash`
(kept for exactly one generation — see rotation below). Random-named
(`autoname: hash`), System Manager only — users never see or touch this
doctype directly, it's purely an implementation detail behind the API.

### JWT signing (`auth/jwt_utils.py`)

`PyJWT`, algorithm `HS256`. Signing keys live in `site_config.json`, not
hardcoded, so they can be rotated without a deploy:

```json
{
  "retail_sop_jwt_keys": { "2026-01": "<random secret>" },
  "retail_sop_jwt_active_kid": "2026-01"
}
```

Only `retail_sop_jwt_active_kid` signs *new* tokens; `decode_access_token`
looks up the right secret via the `kid` carried in the JWT header, so
multiple keys can be valid for verification simultaneously. **To rotate**:
add a new kid/secret pair, point `retail_sop_jwt_active_kid` at the new
one, and keep the old kid's secret in the map until every token signed
with it has expired (one `access_token_ttl()` window after the switch) —
then remove it. Payload: `{"sub": user, "sid": <Auth Session name>,
"type": "access", "iat", "exp"}`.

### Endpoints (`auth/api.py`)

All `@frappe.whitelist(allow_guest=True, methods=["POST"])` except `me`
and `logout_all`, which require an already-authenticated request (a
valid `Authorization` header, processed by the middleware below) and use
plain `@frappe.whitelist()`.

| Method | Behavior |
|---|---|
| `login(usr, pwd, device_id, device_name=None)` | Verifies credentials via Frappe's own `check_password` (never a custom check), rejects disabled users and anyone without an allowed role (`ALLOWED_ROLES` in `auth/api.py` — Food Court Supervisor/Manager, Store Operator, + System Manager as an admin escape hatch), inserts a new `Auth Session`, returns `{access_token, refresh_token, token_type: "Bearer", expires_in, user}` |
| `refresh_token(refresh_token)` | Hashes the presented token, rotates it — see below |
| `logout(refresh_token)` | Revokes the matching session; always returns `{success: true}` regardless of whether the token was recognized, so it never leaks that information |
| `logout_all()` | Revokes every non-revoked `Auth Session` for `frappe.session.user` |
| `me()` | Returns the same user-profile shape as `login`, for a silent session restore on app boot |

**Refresh rotation + reuse/replay detection** — the security-sensitive
part, verified in isolation against the exact scenarios below before
being wired into the doctype:

1. Normal case: the presented token's hash matches a live session's
   `refresh_token_hash`. Rotate — move the current hash into
   `prev_refresh_token_hash`, generate and hash a new refresh token,
   issue a new access token.
2. Presented token matches a session's `prev_refresh_token_hash` instead
   (i.e. it was already rotated out exactly one generation ago): treated
   as theft — the session is revoked immediately and the call rejected.
   This is what catches a leaked/stolen refresh token being used after
   the legitimate client already rotated past it.
3. Presented token matches neither (rotated out *more* than one
   generation ago, or never existed): rejected as invalid, no session
   identified to revoke (there's nothing more specific to do — this is
   the "kept for exactly one generation" tradeoff, not a full history).
4. Two concurrent `refresh_token` calls racing on the same session: the
   loser's `doc.save()` raises `frappe.TimestampMismatchError` (Frappe's
   normal optimistic-concurrency check) — handled as a clean "already
   used by another request, retry" error, not a revocation.

### The bypass (`auth/middleware.py`, `before_request` hook)

```python
before_request = ["retail_sop.auth.middleware.authenticate_request"]
```

Runs on **every** request. Reads `Authorization: Bearer <token>`,
decodes+verifies the JWT (signature, expiry, `type == "access"`), then
re-checks that session's `Auth Session.revoked_at` in the DB — this one
DB read is what makes `logout` take effect immediately rather than
waiting for the JWT to expire on its own. If everything checks out,
`frappe.set_user(user)` makes the rest of the request run as that real
user, with roles evaluated live and normally by everything downstream —
`retail_sop/api.py`'s existing `_check_auth()` and default
`@frappe.whitelist()` methods work against this exactly as if a cookie
session had authenticated them, no changes needed there. If there's
no/garbage/expired header, the hook does nothing — the request proceeds
as Guest and any protected endpoint's own `allow_guest=False` (the
default) rejects it with a normal `PermissionError`. No `sid` cookie is
ever involved, so Frappe's CSRF check (which only triggers for
cookie-backed sessions) never engages either.

The whole hook is wrapped in a broad `except Exception` that
`frappe.log_error`s and falls through to Guest — a `before_request` hook
runs for literally every request on the site (Desk included), so a bug
or a missing `site_config.json` key here must never be able to take the
whole site down; worst case is just an authentication attempt failing
safe instead of crashing.

**Gotcha, called out explicitly in the code**: `frappe.set_user()` resets
`frappe.local.form_dict` as a side effect (it assumes it runs *before*
the request body is parsed). Since this hook runs *after* parsing, the
middleware saves and restores `frappe.local.form_dict` around the
`set_user()` call — otherwise every request's params would silently
vanish the moment a valid bearer token was presented.

### Setup

All of this lives in `site_config.json` (per-site, **not**
`common_site_config.json`) — there is no other credential store, OAuth
app registration, or bench-level secret involved.

**Required** before `login()` will work at all:
```bash
bench --site your-site set-config retail_sop_jwt_keys '{"2026-01": "<random secret>"}' --parse
bench --site your-site set-config retail_sop_jwt_active_kid "2026-01"
```
Generate the secret with e.g. `openssl rand -base64 48`. See "JWT
signing" above for what `retail_sop_jwt_keys` being a `{kid: secret}`
map buys you (rotation without breaking already-issued tokens).

**Optional**, both already have sane defaults:
```bash
bench --site your-site set-config retail_sop_access_token_ttl_seconds 2400   # 40 min
bench --site your-site set-config retail_sop_refresh_token_ttl_days 30
```

**Also required, but not a JWT setting**: if the frontend is served from
a different origin than this site (the normal case — see the
pixel-perfect repo, deployed separately), the browser will block every
request regardless of a valid token unless CORS is enabled:
```bash
bench --site your-site set-config allow_cors "https://your-frontend-origin.example.com"
```

### Troubleshooting

- **`Failed to get method for command retail_sop.auth.api.login with No
  module named 'retail_sop.auth'`** — the site's installed app code is
  stale; `retail_sop/auth/` exists in git but hasn't reached the
  bench's `apps/retail_sop` checkout yet, or the already-running
  workers haven't picked it up. `cd apps/retail_sop && git pull`, then
  from the bench root: `bench --site your-site migrate`,
  `bench build --app retail_sop`, `bench restart` — the restart matters,
  since already-running Python processes cache what modules exist and
  won't see a new subpackage without one. If `git pull` refuses because
  of local changes to `retail_sop/fixtures/*.json`, that's almost always
  fixture-export drift (something ran `bench export-fixtures` and
  rewrote the file with the live DB row, same values, extra default
  fields) rather than an intentional edit — `git diff` the file to
  confirm, then `git checkout -- <file>` and pull again.
- **401 on `login()`** — this is `frappe.AuthenticationError`, which
  this endpoint only raises from `check_password()` (wrong username or
  password) or the disabled-user check in `_ensure_allowed()` — **not**
  from missing JWT config. `check_password()` runs first, before
  `encode_access_token()` ever touches `retail_sop_jwt_keys`, so a 401
  here means the credentials themselves are the problem (or the account
  never had a password set via Frappe's invite flow), not a setup step
  you've missed. A role that isn't in `ALLOWED_ROLES` fails differently
  (403, `frappe.PermissionError`), and missing/incomplete JWT key config
  fails differently again (a plain `frappe.throw` naming the missing
  `site_config.json` key) — both only reachable *after* the password
  check passes. Check the response body's `_server_messages` for the
  exact message rather than going by HTTP status alone.

---

## License

MIT
