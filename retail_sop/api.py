"""Whitelisted REST API surface consumed by the pixel-perfect frontend
(https://github.com/Vijay-micronxt/pixel-perfect).

This module's function names, parameters, and return shapes are written to
match that frontend's data-access layer 1:1 - see its src/services/types.ts
and src/services/sopService.ts, which document the exact contract every
screen is built against (currently backed by in-memory mock data there;
this module is what the fetch() calls swap in for it). Method name mapping:

    frontend (sopService.ts)         backend (this module)
    -------------------------------  -------------------------------
    listOutlets()                    list_outlets()
    listCategories()                 list_categories()
    getTodayChecklists()             get_today_checklists()
    getChecklist(name)               get_checklist(name)
    getHistory(from, to)             get_history(from_date, to_date)
    getVerificationQueue()           get_verification_queue()
    getDeviations(outlet)            get_deviations(outlet)
    getDashboardData()               get_dashboard_data()
    saveChecklistRow(name, sr_no, u) save_checklist_row(checklist_name, sr_no, ...)
    submitChecklist(name)            submit_checklist(name)
    verifyChecklist(name)            verify_checklist(name)
    createDeviation(input)           create_deviation(...)
    updateDeviationStatus(name, s)   update_deviation_status(name, resolution_status)

Auth: the frontend authenticates via the JWT bearer-token flow in
retail_sop/auth/ (login/refresh/logout - see its module docstrings and
README §12), not Frappe's cookie-session login. retail_sop.auth.middleware
runs before every request and, given a valid Authorization header, calls
frappe.set_user() so frappe.session.user below is already the real user
by the time these handlers run. `_check_auth` is kept as a single choke
point regardless, both as a defensive check and so the strategy could be
swapped again later without touching every method.

All responses are plain dict/list JSON - no Frappe Document objects or
internal metadata are returned directly.
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, get_datetime, getdate, now_datetime, nowtime, today

from retail_sop.retail_sop.doctype.shift_checklist.shift_checklist import (
	ShiftChecklistValidationError,
)


def _check_auth():
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication required"), frappe.AuthenticationError)


def _check_staff_role():
	"""Blocks the Supervisor/Manager checklist-listing endpoints from a
	Store Operator caller. frappe.get_all() (used throughout this module)
	does not enforce Frappe's permission engine on its own - and Store
	Operator deliberately has zero doctype-level permission on Shift
	Checklist, relying only on get_my_store_summary()'s manual outlet
	check - so without this, a Store Operator account can see every
	outlet's checklists through these endpoints instead of being blocked.
	"""
	roles = set(frappe.get_roles(frappe.session.user))
	if not roles & {"Food Court Supervisor", "Food Court Manager", "System Manager"}:
		frappe.throw(_("Not permitted."), frappe.PermissionError)


def _format_time(value):
	"""HH:MM, matching the frontend's display convention. Accepts a
	Datetime, Time (timedelta/str), or plain string value."""
	if not value:
		return None
	try:
		return get_datetime(value).strftime("%H:%M")
	except Exception:
		s = str(value)
		return s[:5] if len(s) >= 5 else s


# Single source of truth for the values _computed_status() below can
# return - exposed via get_checklist_status_options() so the frontend's
# status dropdown updates automatically if this list ever changes, instead
# of a hardcoded copy drifting out of sync with the backend.
CHECKLIST_STATUS_OPTIONS = ["Draft", "In Progress", "Missed", "Submitted", "Verified", "Escalated"]

# Same idea as CHECKLIST_STATUS_OPTIONS - kept here as the one source of
# truth for a shift-type filter dropdown, instead of a copy hardcoded on the
# frontend that could drift from the Shift Checklist doctype's own Select
# options.
SHIFT_TYPE_OPTIONS = ["Pre-Opening", "Mid-Day", "Closing", "Weekly Audit"]


def _computed_status(doc):
	"""Maps our docstatus/workflow_state onto the frontend's ChecklistStatus
	union (Draft/In Progress/Missed/Submitted/Verified/Escalated) - the
	doctype's own `status` field is kept for internal/Desk bookkeeping only
	and is not the source of truth for what the API reports.
	"""
	if doc.docstatus == 2:
		return "Draft"
	if doc.docstatus == 0:
		if doc.cutoff_time and now_datetime() > get_datetime(f"{doc.date} {doc.cutoff_time}"):
			return "Missed"
		return "In Progress" if any(row.status for row in doc.items) else "Draft"
	if doc.workflow_state == "Verified":
		return "Verified"
	if doc.failed_checks:
		return "Escalated"
	return "Submitted"


def _get_category_options():
	# Categories are ERP-managed master data (Checklist Category), not a
	# fixed list - any Food Court Manager can add/retire one from the Desk
	# and it shows up here immediately, no code change needed.
	return frappe.get_all(
		"Checklist Category", filters={"active": 1}, pluck="name", order_by="name"
	)


def _serialize_checklist(doc):
	items = []
	for row in doc.items:
		# frappe.get_cached_doc() loads a full Document, which triggers
		# Frappe's permission engine - and Checklist Template Item is a
		# child-table doctype with no permissions of its own (it can only
		# normally be reached through its parent Checklist Template), so
		# that check fails with "Please specify a valid parent DocType"
		# for any non-Administrator caller. frappe.db.get_value() is a raw
		# field read with no Document-level permission check, which is all
		# we need here - we only read a few fields, never write.
		template_item = (
			frappe.db.get_value(
				"Checklist Template Item",
				row.template_item,
				[
					"input_type",
					"min_value",
					"max_value",
					"is_mandatory",
					"requires_photo",
					"positive_label",
					"negative_label",
				],
				as_dict=True,
			)
			if row.template_item
			else None
		)
		items.append(
			{
				"sr_no": row.sr_no,
				"check_description": row.check_description,
				"category": row.category,
				"standard": row.standard,
				"input_type": template_item.input_type if template_item else "Tick",
				"min_value": template_item.min_value if template_item else None,
				"max_value": template_item.max_value if template_item else None,
				"is_mandatory": 1 if (template_item and template_item.is_mandatory) else 0,
				"requires_photo": 1 if (template_item and template_item.requires_photo) else 0,
				# Per-item override of the generic "OK"/"Not OK" button wording
				# (e.g. "Available"/"Not Available") - the sheet uses different
				# wording per section even though the underlying OK/Not OK/NA
				# value stored is always the same. None/blank means "use the
				# default", not "no answer".
				"positive_label": (template_item.positive_label if template_item else None) or None,
				"negative_label": (template_item.negative_label if template_item else None) or None,
				"status": row.status or None,
				"reading": row.reading,
				"checked_at": _format_time(row.checked_at),
				"checked_by": row.checked_by,
				"remarks": row.remarks,
				"attachment": row.attachment,
				"vendor": row.vendor,
			}
		)

	return {
		"name": doc.name,
		"date": str(doc.date),
		"shift_type": doc.shift_type,
		"checklist_scope": doc.checklist_scope,
		"location": doc.location,
		"supervisor": doc.supervisor,
		"status": _computed_status(doc),
		"compliance_score": doc.compliance_score,
		"total_checks": doc.total_checks,
		"failed_checks": doc.failed_checks,
		"completion_confirmed": 1 if doc.completion_confirmed else 0,
		"items": items,
	}


def _serialize_deviation(doc):
	return {
		"name": doc.name,
		"date": str(doc.date),
		"time": _format_time(doc.time),
		"outlet": doc.outlet,
		"category": doc.category,
		"severity": doc.severity,
		"issue": doc.issue,
		"action_taken": doc.action_taken,
		"photo": doc.photo,
		"resolution_status": doc.resolution_status,
		"escalated_to": doc.escalated_to,
		"closed_by": doc.closed_by,
		"closed_on": str(doc.closed_on) if doc.closed_on else None,
		"responsible_person": doc.responsible_person,
		"expected_resolution_time": str(doc.expected_resolution_time) if doc.expected_resolution_time else None,
	}


def _get_checklist_names(conditions, order_by, limit=None, offset=None):
	kwargs = {}
	if limit:
		kwargs["limit_page_length"] = cint(limit)
	if offset:
		kwargs["limit_start"] = cint(offset)
	return frappe.get_all("Shift Checklist", filters=conditions, pluck="name", order_by=order_by, **kwargs)


# ---------------------------------- reads -----------------------------------


@frappe.whitelist()
def list_outlets(limit=None, offset=None):
	_check_auth()
	kwargs = {}
	if limit:
		kwargs["limit_page_length"] = cint(limit)
	if offset:
		kwargs["limit_start"] = cint(offset)
	return frappe.get_all(
		"Outlet", filters={"active": 1}, pluck="outlet_name", order_by="outlet_name", **kwargs
	)


@frappe.whitelist()
def list_categories(limit=None, offset=None):
	_check_auth()
	kwargs = {}
	if limit:
		kwargs["limit_page_length"] = cint(limit)
	if offset:
		kwargs["limit_start"] = cint(offset)
	return frappe.get_all(
		"Checklist Category", filters={"active": 1}, pluck="name", order_by="name", **kwargs
	)


@frappe.whitelist()
def get_checklist_status_options():
	"""The full set of values _computed_status() can return, for populating
	a checklist status filter dropdown. Fixed/computed, not doctype master
	data, but exposed as an API anyway so the frontend never hardcodes its
	own copy - if this list changes here, the dropdown picks it up on next
	load with no frontend code change needed.
	"""
	_check_auth()
	return CHECKLIST_STATUS_OPTIONS


@frappe.whitelist()
def get_shift_type_options():
	"""The full set of Shift Checklist shift_type values, for populating a
	shift-type filter dropdown (e.g. isolating "Weekly Audit" from the daily
	shift types) - see SHIFT_TYPE_OPTIONS.
	"""
	_check_auth()
	return SHIFT_TYPE_OPTIONS


@frappe.whitelist()
def get_deviation_resolution_status_options():
	"""Checklist Deviation.resolution_status's Select options, read straight
	from the doctype's own field metadata - genuinely live, so even a
	Desk-side edit to that field (via Customize Form) shows up here with no
	code change or deploy at all.
	"""
	_check_auth()
	options = frappe.get_meta("Checklist Deviation").get_field("resolution_status").options
	return [o for o in (options or "").split("\n") if o]


@frappe.whitelist()
def get_history_status_options():
	"""Values for get_history()'s workflow_state filter. Not all of
	Shift Checklist.workflow_state's options (Draft/Submitted/Verified) -
	History only ever returns docstatus=1 (submitted) records, so Draft
	isn't a meaningful filter choice there; Submitted/Verified are the only
	two that can actually occur.
	"""
	_check_auth()
	return ["Submitted", "Verified"]


@frappe.whitelist()
def get_today_checklists(
	date=None, outlet=None, status=None, checklist_scope=None, shift_type=None, limit=None, offset=None
):
	_check_auth()
	_check_staff_role()
	conditions = [["date", "=", date or today()], ["docstatus", "!=", 2]]
	if outlet and outlet != "All":
		conditions.append(["location", "=", outlet])
	if checklist_scope:
		conditions.append(["checklist_scope", "=", checklist_scope])
	if shift_type and shift_type != "All":
		conditions.append(["shift_type", "=", shift_type])
	# status (Draft/In Progress/Missed/Submitted/Verified/Escalated) is
	# computed, not stored (see _computed_status) - so it's filtered here
	# after serializing rather than in the frappe.get_all() query above.
	# Fine at this scale: one outlet-day's worth of checklists, not the
	# whole table.
	names = _get_checklist_names(conditions, "creation desc")
	checklists = [_serialize_checklist(frappe.get_doc("Shift Checklist", n)) for n in names]
	if status and status != "All":
		checklists = [c for c in checklists if c["status"] == status]
	if offset:
		checklists = checklists[cint(offset):]
	if limit:
		checklists = checklists[: cint(limit)]
	return checklists


@frappe.whitelist()
def get_checklist(name):
	_check_auth()
	_check_staff_role()
	if not frappe.db.exists("Shift Checklist", name):
		return None
	return _serialize_checklist(frappe.get_doc("Shift Checklist", name))


@frappe.whitelist()
def get_history(
	from_date=None, to_date=None, workflow_state=None, outlet=None, shift_type=None, limit=50, offset=0
):
	_check_auth()
	_check_staff_role()
	conditions = [["docstatus", "=", 1]]
	if from_date:
		conditions.append(["date", ">=", from_date])
	if to_date:
		conditions.append(["date", "<=", to_date])
	if workflow_state and workflow_state != "All":
		conditions.append(["workflow_state", "=", workflow_state])
	if outlet and outlet != "All":
		conditions.append(["location", "=", outlet])
	if shift_type and shift_type != "All":
		conditions.append(["shift_type", "=", shift_type])
	names = _get_checklist_names(conditions, "date desc", limit, offset)
	return [_serialize_checklist(frappe.get_doc("Shift Checklist", n)) for n in names]


def _compliance_by_date(rows):
	"""rows: an iterable of {date, compliance_score} - averages
	compliance_score per calendar date and returns points sorted oldest
	to newest, the shape a line chart wants. Shared by get_history_chart
	and get_my_store_history_chart below.
	"""
	by_date = {}
	for row in rows:
		by_date.setdefault(str(row.date), []).append(row.compliance_score or 0)
	return [
		{"date": date, "compliance": round(sum(scores) / len(scores), 2)}
		for date, scores in sorted(by_date.items())
	]


@frappe.whitelist()
def get_history_chart(from_date=None, to_date=None, workflow_state=None, outlet=None):
	"""Compliance-trend aggregate backing the chart on the History screen -
	same filters as get_history() above, but summarized (average
	compliance_score per date) instead of paginated full records. The
	History list only ever has one page of records loaded client-side at
	a time (see sopService.ts's useInfiniteQuery), which isn't enough to
	chart the whole filtered range - this intentionally does its own
	unpaginated fetch rather than trying to derive the chart from
	whatever page happens to be in view.
	"""
	_check_auth()
	_check_staff_role()
	conditions = [["docstatus", "=", 1]]
	if from_date:
		conditions.append(["date", ">=", from_date])
	if to_date:
		conditions.append(["date", "<=", to_date])
	if workflow_state and workflow_state != "All":
		conditions.append(["workflow_state", "=", workflow_state])
	if outlet and outlet != "All":
		conditions.append(["location", "=", outlet])

	rows = frappe.get_all(
		"Shift Checklist", filters=conditions, fields=["date", "compliance_score"]
	)
	return _compliance_by_date(rows)


@frappe.whitelist()
def get_verification_queue(outlet=None, from_date=None, to_date=None, shift_type=None, limit=50, offset=0):
	_check_auth()
	_check_staff_role()
	conditions = [["docstatus", "=", 1], ["workflow_state", "!=", "Verified"]]
	if outlet and outlet != "All":
		conditions.append(["location", "=", outlet])
	if from_date:
		conditions.append(["date", ">=", from_date])
	if to_date:
		conditions.append(["date", "<=", to_date])
	if shift_type and shift_type != "All":
		conditions.append(["shift_type", "=", shift_type])
	names = _get_checklist_names(conditions, "date asc", limit, offset)
	return [_serialize_checklist(frappe.get_doc("Shift Checklist", n)) for n in names]


@frappe.whitelist()
def get_deviations(
	outlet=None,
	resolution_status=None,
	shift_checklist=None,
	from_date=None,
	to_date=None,
	limit=50,
	offset=0,
):
	_check_auth()
	_check_staff_role()
	filters = {}
	if outlet and outlet != "All":
		filters["outlet"] = outlet
	if resolution_status and resolution_status != "All":
		filters["resolution_status"] = resolution_status
	if shift_checklist:
		filters["shift_checklist"] = shift_checklist
	if from_date:
		filters["date"] = [">=", from_date]
	if to_date:
		filters["date"] = ["between", [from_date, to_date]] if from_date else ["<=", to_date]
	kwargs = {}
	if limit:
		kwargs["limit_page_length"] = cint(limit)
	if offset:
		kwargs["limit_start"] = cint(offset)
	names = frappe.get_all(
		"Checklist Deviation", filters=filters, pluck="name", order_by="date desc, creation desc", **kwargs
	)
	return [_serialize_deviation(frappe.get_doc("Checklist Deviation", n)) for n in names]


# --------------------------------- exports ------------------------------------
# Plain JSON, same as every other endpoint in this file - the frontend
# builds the actual xlsx/pdf client-side from this data, nothing is
# generated server-side. Same filters as the matching read endpoint above
# (get_history / get_deviations), just unpaginated - an export always
# covers the whole filtered range, never a page of it. Unpaginated is fine
# at this app's scale (one food court, a handful of outlets); revisit if
# that stops being true.
#
# Response shape is {"columns": [...], "rows": [...]} rather than a bare
# array - `columns` is the single source of truth for which keys exist,
# their order, and their display label. The frontend's Excel/PDF builder
# should iterate `columns` generically (row[col.key] under col.label)
# instead of hardcoding key names - that's what actually lets a new field
# show up in the exported file the moment it's added here, with zero
# frontend code change. Add a field to a row dict without also adding it
# to `columns` and it silently won't appear in the export - the two must
# be kept in sync by construction, which is why each row is built directly
# from the same list COLUMNS is derived from below, not independently.


CHECKLIST_REPORT_COLUMNS = [
	{"key": "checklist_id", "label": "Checklist ID"},
	{"key": "date", "label": "Date"},
	{"key": "shift_type", "label": "Shift Type"},
	{"key": "outlet", "label": "Outlet"},
	{"key": "supervisor", "label": "Supervisor"},
	{"key": "status", "label": "Status"},
	{"key": "compliance_score", "label": "Compliance Score (%)"},
	{"key": "total_checks", "label": "Total Checks"},
	{"key": "failed_checks", "label": "Failed Checks"},
]

DEVIATION_REPORT_COLUMNS = [
	{"key": "name", "label": "Deviation ID"},
	{"key": "date", "label": "Date"},
	{"key": "time", "label": "Time"},
	{"key": "outlet", "label": "Outlet"},
	{"key": "category", "label": "Category"},
	{"key": "severity", "label": "Severity"},
	{"key": "issue", "label": "Issue"},
	{"key": "action_taken", "label": "Action Taken"},
	{"key": "responsible_person", "label": "Responsible Person"},
	{"key": "expected_resolution_time", "label": "Expected Resolution Time"},
	{"key": "resolution_status", "label": "Resolution Status"},
	{"key": "escalated_to", "label": "Escalated To"},
	{"key": "closed_by", "label": "Closed By"},
	{"key": "closed_on", "label": "Closed On"},
]


@frappe.whitelist()
def export_checklist_report(
	from_date=None, to_date=None, outlet=None, workflow_state=None, status=None, shift_type=None
):
	"""Full (unpaginated) checklist history matching the given filters, as
	{"columns": [...], "rows": [...]}. See the section comment above for why
	the shape carries column metadata.

	Two different status filters, because the frontend has two different
	notions of "status" that don't overlap:
	  - workflow_state: the doctype's own field (Draft/Submitted/Verified) -
	    what History's filter uses.
	  - status: the same *computed* status get_today_checklists()/
	    _computed_status() use (adds Missed/In Progress/Escalated, which
	    aren't real workflow_state values) - what the Verification Queue's
	    "Missed" mode needs to export the same rows it shows on screen.
	docstatus is no longer hardcoded to 1 (submitted only) - that silently
	excluded every Missed checklist (docstatus=0, never submitted) from
	the export regardless of any filter, even though it's a real status
	the UI shows and lets you filter to.
	"""
	_check_auth()
	_check_staff_role()

	conditions = [["docstatus", "!=", 2]]
	if from_date:
		conditions.append(["date", ">=", from_date])
	if to_date:
		conditions.append(["date", "<=", to_date])
	if workflow_state and workflow_state != "All":
		conditions.append(["workflow_state", "=", workflow_state])
	if outlet and outlet != "All":
		conditions.append(["location", "=", outlet])
	if shift_type and shift_type != "All":
		conditions.append(["shift_type", "=", shift_type])

	names = frappe.get_all("Shift Checklist", filters=conditions, pluck="name", order_by="date desc")
	checklists = [_serialize_checklist(frappe.get_doc("Shift Checklist", n)) for n in names]
	if status and status != "All":
		checklists = [c for c in checklists if c["status"] == status]

	return {
		"columns": CHECKLIST_REPORT_COLUMNS,
		"rows": [
			{
				"checklist_id": c["name"],
				"date": c["date"],
				"shift_type": c["shift_type"],
				"outlet": c["location"],
				"supervisor": c["supervisor"],
				"status": c["status"],
				"compliance_score": c["compliance_score"],
				"total_checks": c["total_checks"],
				"failed_checks": c["failed_checks"],
			}
			for c in checklists
		],
	}


@frappe.whitelist()
def export_deviation_report(
	from_date=None, to_date=None, outlet=None, resolution_status=None, shift_checklist=None
):
	"""Full (unpaginated) deviations matching the given filters, as
	{"columns": [...], "rows": [...]} - same filters as get_deviations(),
	rows in the same shape _serialize_deviation() already returns.
	"""
	_check_auth()
	_check_staff_role()

	filters = {}
	if outlet and outlet != "All":
		filters["outlet"] = outlet
	if resolution_status and resolution_status != "All":
		filters["resolution_status"] = resolution_status
	if shift_checklist:
		filters["shift_checklist"] = shift_checklist
	if from_date:
		filters["date"] = [">=", from_date]
	if to_date:
		filters["date"] = ["between", [from_date, to_date]] if from_date else ["<=", to_date]

	names = frappe.get_all(
		"Checklist Deviation", filters=filters, pluck="name", order_by="date desc, creation desc"
	)
	return {
		"columns": DEVIATION_REPORT_COLUMNS,
		"rows": [_serialize_deviation(frappe.get_doc("Checklist Deviation", n)) for n in names],
	}


# ------------------------------ store operator -------------------------------
# Read-only, self-scoped to the caller's own outlet - deliberately separate
# from the supervisor/manager surface above. The Store Operator role holds
# no doctype-level read permission on Shift Checklist at all (see the Role
# fixture / README §4), so the outlet scoping below - not the permission
# engine - is what limits access; ignore_permissions=True is used
# accordingly, the same way other endpoints in this file already use it for
# writes.


def _get_my_outlet():
	outlet = frappe.db.get_value("Outlet", {"store_operator": frappe.session.user}, "outlet_name")
	if not outlet:
		frappe.throw(_("Your account is not linked to a store."), frappe.PermissionError)
	return outlet


@frappe.whitelist()
def get_my_outlet():
	"""The single Outlet the calling user is tagged as Store Operator for.
	Lets the frontend skip an outlet picker (e.g. on the Raise Deviation
	screen) instead of showing every outlet in the system to someone who
	only has one.
	"""
	_check_auth()
	return {"outlet": _get_my_outlet()}


@frappe.whitelist()
def get_my_deviations(
	resolution_status=None,
	shift_checklist=None,
	from_date=None,
	to_date=None,
	limit=50,
	offset=0,
):
	"""Checklist Deviations for the single Outlet the calling user is the
	store_operator of - the Store Operator equivalent of get_deviations(),
	scoped to their one store instead of every outlet.
	"""
	_check_auth()

	outlet = _get_my_outlet()
	filters = {"outlet": outlet}
	if resolution_status and resolution_status != "All":
		filters["resolution_status"] = resolution_status
	if shift_checklist:
		filters["shift_checklist"] = shift_checklist
	if from_date:
		filters["date"] = [">=", from_date]
	if to_date:
		filters["date"] = ["between", [from_date, to_date]] if from_date else ["<=", to_date]
	kwargs = {}
	if limit:
		kwargs["limit_page_length"] = cint(limit)
	if offset:
		kwargs["limit_start"] = cint(offset)
	names = frappe.get_all(
		"Checklist Deviation",
		filters=filters,
		pluck="name",
		order_by="date desc, creation desc",
		ignore_permissions=True,
		**kwargs,
	)
	return [_serialize_deviation(frappe.get_doc("Checklist Deviation", n)) for n in names]


@frappe.whitelist()
def get_my_store_summary():
	"""Hygiene checks + an overall rating for the single Outlet the calling
	user is the store_operator of. Throws if the account isn't linked to a
	store. Only exposes Hygiene-category rows and a compliance-score
	average - not the full checklist detail the supervisor/manager
	endpoints return.
	"""
	_check_auth()

	outlet = frappe.db.get_value("Outlet", {"store_operator": frappe.session.user}, "outlet_name")
	if not outlet:
		frappe.throw(_("Your account is not linked to a store."), frappe.PermissionError)

	# Last 30 submitted checklists for this outlet - the "rating" is their
	# average compliance_score. Window/definition not specified beyond
	# "rating"; adjust here if the product wants e.g. a 30-day window
	# instead of a fixed checklist count, or the latest score instead of
	# an average.
	checklists = frappe.get_all(
		"Shift Checklist",
		filters={"location": outlet, "docstatus": 1},
		fields=["name", "date", "compliance_score"],
		order_by="date desc",
		limit_page_length=30,
		ignore_permissions=True,
	)

	hygiene_checks = []
	for checklist in checklists:
		doc = frappe.get_doc("Shift Checklist", checklist.name)
		for row in doc.items:
			if row.category != "Hygiene":
				continue
			hygiene_checks.append(
				{
					"date": str(doc.date),
					"check_description": row.check_description,
					"status": row.status,
					"remarks": row.remarks,
				}
			)

	rating = (
		round(sum(c.compliance_score for c in checklists) / len(checklists), 2)
		if checklists
		else 0.0
	)

	return {
		"outlet": outlet,
		"rating": rating,
		"hygiene_checks": hygiene_checks,
	}


@frappe.whitelist()
def get_my_store_checklists(date=None, shift_type=None, limit=None, offset=None):
	"""Shift Checklists (default: today's) for the single Outlet the calling
	user is the store_operator of - the Store Operator equivalent of
	get_today_checklists(), scoped to their one store instead of every
	outlet. No outlet param - always their own store. Throws if the account
	isn't linked to a store. Unlike get_my_store_summary() this returns full
	checklist detail (all categories, not just Hygiene), since seeing and
	filling in their own store's checklist is the actual point of this
	endpoint.
	"""
	_check_auth()

	outlet = _get_my_outlet()

	kwargs = {}
	if limit:
		kwargs["limit_page_length"] = cint(limit)
	if offset:
		kwargs["limit_start"] = cint(offset)
	filters = {"location": outlet, "date": date or today(), "docstatus": ["!=", 2]}
	if shift_type and shift_type != "All":
		filters["shift_type"] = shift_type
	names = frappe.get_all(
		"Shift Checklist",
		filters=filters,
		pluck="name",
		order_by="creation desc",
		ignore_permissions=True,
		**kwargs,
	)
	return [_serialize_checklist(frappe.get_doc("Shift Checklist", n)) for n in names]


@frappe.whitelist()
def get_my_store_history(from_date=None, to_date=None, workflow_state=None, limit=50, offset=0):
	"""Submitted Shift Checklist history for the single Outlet the calling
	user is the store_operator of - the Store Operator equivalent of
	get_history(), scoped to their one store instead of every outlet.
	Throws if the account isn't linked to a store.
	"""
	_check_auth()

	outlet = frappe.db.get_value("Outlet", {"store_operator": frappe.session.user}, "outlet_name")
	if not outlet:
		frappe.throw(_("Your account is not linked to a store."), frappe.PermissionError)

	conditions = [["location", "=", outlet], ["docstatus", "=", 1]]
	if from_date:
		conditions.append(["date", ">=", from_date])
	if to_date:
		conditions.append(["date", "<=", to_date])
	if workflow_state and workflow_state != "All":
		conditions.append(["workflow_state", "=", workflow_state])
	names = _get_checklist_names(conditions, "date desc", limit, offset)
	return [_serialize_checklist(frappe.get_doc("Shift Checklist", n)) for n in names]


@frappe.whitelist()
def get_my_store_history_chart(from_date=None, to_date=None, workflow_state=None):
	"""Store Operator equivalent of get_history_chart(), scoped to their
	one outlet - same relationship as get_my_store_history() has to
	get_history(). Throws if the account isn't linked to a store.
	"""
	_check_auth()

	outlet = frappe.db.get_value("Outlet", {"store_operator": frappe.session.user}, "outlet_name")
	if not outlet:
		frappe.throw(_("Your account is not linked to a store."), frappe.PermissionError)

	conditions = [["location", "=", outlet], ["docstatus", "=", 1]]
	if from_date:
		conditions.append(["date", ">=", from_date])
	if to_date:
		conditions.append(["date", "<=", to_date])
	if workflow_state and workflow_state != "All":
		conditions.append(["workflow_state", "=", workflow_state])

	rows = frappe.get_all(
		"Shift Checklist", filters=conditions, fields=["date", "compliance_score"]
	)
	return _compliance_by_date(rows)


@frappe.whitelist()
def get_dashboard_data():
	_check_auth()
	_check_staff_role()
	return {
		"complianceTrend": _dashboard_compliance_trend(),
		"deviationsByOutlet": _dashboard_deviations_by_outlet(),
		"vendorScorecard": _dashboard_vendor_scorecard(),
		"repeatFailures": _dashboard_repeat_failures(),
		"escalations": _dashboard_escalations(),
	}


@frappe.whitelist()
def get_outlet_closing_status(date=None):
	"""For every active Outlet: whether an Outlet-scope Closing checklist
	exists for `date` (today if omitted) and what state it's in - backs
	the food-court-wide Closing checklist's per-outlet status table
	(source SOP: "Outlet | Closing Checklist Done | Sales Closed | Kitchen
	Closed | Issue"). Deliberately **read-only reference data derived from
	each outlet's own QSR-level submission**, not a second place to
	manually re-enter the same information - see backend README §8.

	This app doesn't separately track "sales closed"/"kitchen closed" as
	distinct facts (only whether the Closing checklist itself was
	submitted/verified), so those two sub-columns from the source sheet
	collapse into one `status` here - flagged as a simplification, not a
	gap: splitting them out would need new fields on Shift Checklist with
	no current use beyond mirroring this one table.
	"""
	_check_auth()
	_check_staff_role()
	date = getdate(date) if date else getdate()

	outlets = frappe.get_all("Outlet", filters={"active": 1}, fields=["name", "outlet_name"])
	checklists = frappe.get_all(
		"Shift Checklist",
		filters={
			"checklist_scope": "Outlet",
			"shift_type": "Closing",
			"date": date,
			"docstatus": ["!=", 2],
		},
		fields=["location", "docstatus", "workflow_state", "failed_checks"],
	)
	by_outlet = {c.location: c for c in checklists}

	rows = []
	for outlet in outlets:
		checklist = by_outlet.get(outlet.name)
		if not checklist:
			status = "Not Started"
		elif checklist.docstatus == 0:
			status = "In Progress"
		elif checklist.workflow_state == "Verified":
			status = "Verified"
		elif checklist.failed_checks:
			status = "Submitted (Issues Found)"
		else:
			status = "Submitted"
		rows.append({"outlet": outlet.outlet_name, "status": status})
	return rows


@frappe.whitelist()
def get_outlet_scorecard(from_date=None, to_date=None):
	"""Per-outlet average compliance_score and deviation count over
	[from_date, to_date] (defaults to the last 7 days) - backs the
	food-court-wide Weekly checklist's outlet scorecard, same
	derived-not-manually-filled approach as get_outlet_closing_status().

	The source sheet's scorecard splits this into separate Hygiene/Staff/
	Food Safety/Operations columns per outlet. This app's checklist
	categories are open-ended (any business can add its own via the
	Checklist Category doctype, see README §8) rather than a fixed small
	set, so there's no reliable way to bucket every category into exactly
	those four columns without hardcoding one business's taxonomy back
	into this endpoint - flagged as a deliberate simplification: one
	blended compliance score per outlet, not a category breakdown.
	"""
	_check_auth()
	_check_staff_role()
	to_date = getdate(to_date) if to_date else getdate()
	from_date = getdate(from_date) if from_date else add_days(to_date, -6)

	outlets = frappe.get_all("Outlet", filters={"active": 1}, fields=["name", "outlet_name"])
	checklists = frappe.get_all(
		"Shift Checklist",
		filters={
			"checklist_scope": "Outlet",
			"docstatus": 1,
			"date": ["between", [from_date, to_date]],
		},
		fields=["location", "compliance_score"],
	)
	deviations = frappe.get_all(
		"Checklist Deviation",
		filters={"date": ["between", [from_date, to_date]]},
		fields=["outlet"],
	)

	scores_by_outlet = {}
	for c in checklists:
		scores_by_outlet.setdefault(c.location, []).append(c.compliance_score or 0)
	issues_by_outlet = {}
	for d in deviations:
		issues_by_outlet[d.outlet] = issues_by_outlet.get(d.outlet, 0) + 1

	rows = []
	for outlet in outlets:
		scores = scores_by_outlet.get(outlet.name, [])
		compliance = round(sum(scores) / len(scores), 2) if scores else None
		rows.append(
			{
				"outlet": outlet.outlet_name,
				"compliance": compliance,
				"issues": issues_by_outlet.get(outlet.name, 0),
			}
		)
	return rows


# --------------------------------- writes ------------------------------------


def _check_checklist_write_access(doc):
	"""Frappe's own doctype permission check (already run by doc.save()/
	doc.submit() below) only knows "this role can write Shift Checklist" -
	it has no idea *which* checklist, so on its own it can't enforce the
	clean split: Food Court Supervisor fills only Food-Court-scope
	checklists, Store Operator fills only their own outlet's Outlet-scope
	ones. This is the actual gate, same app-layer-enforcement pattern as
	_check_staff_role() elsewhere in this module.
	"""
	roles = set(frappe.get_roles(frappe.session.user))
	if "System Manager" in roles:
		return
	if "Food Court Supervisor" in roles and doc.checklist_scope == "Food Court":
		return
	if "Store Operator" in roles and doc.checklist_scope == "Outlet" and doc.location == _get_my_outlet():
		return
	frappe.throw(_("Not permitted."), frappe.PermissionError)


@frappe.whitelist()
def save_checklist_row(checklist_name, sr_no, status=None, reading=None, remarks=None, attachment=None):
	_check_auth()

	doc = frappe.get_doc("Shift Checklist", checklist_name)
	_check_checklist_write_access(doc)
	if doc.docstatus != 0:
		frappe.throw(_("Cannot update items on a submitted or cancelled Shift Checklist."))

	row = next((r for r in doc.items if cint(r.sr_no) == cint(sr_no)), None)
	if not row:
		frappe.throw(_("Row with Sr No {0} not found in {1}.").format(sr_no, checklist_name))

	if status is not None:
		row.status = status or ""
	if reading is not None:
		row.reading = reading
	if remarks is not None:
		row.remarks = remarks
	if attachment is not None:
		row.attachment = attachment

	if status:
		row.checked_at = now_datetime()
		row.checked_by = frappe.session.user

	doc.save()
	return _serialize_checklist(doc)


@frappe.whitelist()
def submit_checklist(name, confirmed=False):
	"""Validation (mandatory/photo/completeness rules) lives entirely in
	ShiftChecklist.validate() - this just calls submit() and reshapes
	whatever it raised into the frontend's SubmitResponse shape.

	confirmed: the frontend's "I confirm I have personally completed this
	checklist" checkbox - see ShiftChecklist.enforce_completion_confirmed().
	"""
	_check_auth()

	doc = frappe.get_doc("Shift Checklist", name)
	_check_checklist_write_access(doc)
	doc.completion_confirmed = 1 if cint(confirmed) else 0
	# Explicitly driving workflow_state (same pattern as verify_checklist()
	# below) rather than leaving it to on_submit()'s after-the-fact
	# db_set() - that ran too late for
	# ShiftChecklist.enforce_workflow_state_transition() to ever see the
	# Draft->Submitted transition, silently turning that check into dead
	# code. Setting it here makes the backstop actually fire.
	doc.workflow_state = "Submitted"
	try:
		doc.submit()
	except ShiftChecklistValidationError as e:
		errors = [{"row": str(row["sr_no"]), "message": row["message"]} for row in e.rows]
		return {"success": False, "errors": errors}

	return {"success": True}


@frappe.whitelist()
def verify_checklist(name):
	"""Moves a Submitted (or Escalated-but-submitted) checklist to Verified.
	The role check is enforced by ShiftChecklist.enforce_workflow_state_transition()
	in validate() - not duplicated here.
	"""
	_check_auth()

	doc = frappe.get_doc("Shift Checklist", name)
	if doc.docstatus != 1:
		frappe.throw(_("Only a submitted checklist can be verified."))

	doc.workflow_state = "Verified"
	doc.save()
	return {"success": True}


@frappe.whitelist()
def create_deviation(
	outlet,
	category,
	severity,
	issue,
	action_taken,
	photo=None,
	responsible_person=None,
	expected_resolution_time=None,
):
	_check_auth()

	roles = set(frappe.get_roles(frappe.session.user))
	if "Store Operator" in roles and not roles & {
		"Food Court Supervisor",
		"Food Court Manager",
		"System Manager",
	}:
		# A Store Operator can only ever raise a deviation against their own
		# outlet - override whatever the client sent rather than trusting it,
		# same reasoning as _check_checklist_write_access() elsewhere here.
		outlet = _get_my_outlet()

	if not (outlet and category and issue and action_taken):
		frappe.throw(_("Outlet, category, issue and action taken are all required."))
	if severity == "Critical" and not photo:
		frappe.throw(_("A photo is required for critical deviations."))

	doc = frappe.new_doc("Checklist Deviation")
	doc.date = today()
	doc.time = nowtime()
	doc.outlet = outlet
	doc.category = category
	doc.severity = severity
	doc.issue = issue
	doc.action_taken = action_taken
	doc.photo = photo
	doc.responsible_person = responsible_person
	doc.expected_resolution_time = expected_resolution_time
	if severity == "Critical":
		# Frontend default was a placeholder "Area Manager" string; using
		# the real Food Court Manager role instead so this also lines up
		# with the Critical-deviation email notification (see
		# checklist_deviation.py / the Notification fixture).
		doc.escalated_to = "Food Court Manager"

	doc.insert()
	return _serialize_deviation(doc)


@frappe.whitelist()
def update_deviation_status(
	name, resolution_status, responsible_person=None, expected_resolution_time=None
):
	_check_auth()
	_check_staff_role()

	doc = frappe.get_doc("Checklist Deviation", name)
	doc.resolution_status = resolution_status
	if resolution_status == "Closed":
		doc.closed_by = frappe.session.user
		doc.closed_on = today()
	else:
		doc.closed_by = None
		doc.closed_on = None
	# Assignment can be set/changed later while triaging, not just at
	# creation - only touch these when the caller actually passed a value,
	# so a plain status move doesn't wipe out an existing assignment.
	if responsible_person is not None:
		doc.responsible_person = responsible_person
	if expected_resolution_time is not None:
		doc.expected_resolution_time = expected_resolution_time
	doc.save()
	return _serialize_deviation(doc)


@frappe.whitelist()
def list_assignable_users():
	"""Users eligible to be set as a Checklist Deviation's Responsible
	Person - anyone holding one of the three staff roles, not every User
	in the system. Powers a picker on the deviation triage screen instead
	of free-text (which would let the same person end up spelled three
	different ways across deviations).
	"""
	_check_auth()
	user_names = frappe.get_all(
		"Has Role",
		filters={
			"role": ["in", ["Store Operator", "Food Court Supervisor", "Food Court Manager"]],
			"parenttype": "User",
		},
		pluck="parent",
	)
	if not user_names:
		return []
	return frappe.get_all(
		"User",
		filters={"name": ["in", set(user_names)], "enabled": 1},
		fields=["name", "full_name"],
		order_by="full_name",
	)


# ------------------------------- dashboard -----------------------------------
# No date-range params - the frontend's getDashboardData() takes none, so
# each helper below picks its own reporting window. Flagged as an
# assumption: adjust the windows here if the product wants something
# narrower/wider than "last 6 months" / "all time".


def _dashboard_compliance_trend():
	rows = frappe.db.sql(
		"""
		select
			location as outlet,
			date_format(date, '%%b') as month,
			date_format(date, '%%Y-%%m') as month_key,
			avg(compliance_score) as compliance
		from `tabShift Checklist`
		where docstatus = 1 and location is not null
			and date >= date_sub(curdate(), interval 6 month)
		group by location, date_format(date, '%%Y-%%m')
		order by month_key
		""",
		as_dict=True,
	)
	return [
		{"month": r["month"], "outlet": r["outlet"], "compliance": round(flt(r["compliance"]))}
		for r in rows
	]


def _dashboard_deviations_by_outlet():
	categories = _get_category_options()

	rows = frappe.db.sql(
		"select outlet, category, count(*) as count from `tabChecklist Deviation` group by outlet, category",
		as_dict=True,
	)
	by_outlet = {}
	for r in rows:
		entry = by_outlet.setdefault(r["outlet"], {"outlet": r["outlet"]})
		entry[r["category"]] = r["count"]

	result = []
	for outlet, entry in by_outlet.items():
		for category in categories:
			entry.setdefault(category, 0)
		result.append(entry)
	return result


def _dashboard_vendor_scorecard():
	"""Despite the name (inherited from the frontend type), this is an
	outlet-level scorecard - matches how dashboards.tsx actually renders
	it ("Outlet scorecard": outlet, compliance %, deviation count).
	"""
	compliance_rows = frappe.db.sql(
		"""
		select location as outlet, avg(compliance_score) as compliance
		from `tabShift Checklist`
		where docstatus = 1 and location is not null
		group by location
		""",
		as_dict=True,
	)
	deviation_counts = frappe.db.sql(
		"select outlet, count(*) as count from `tabChecklist Deviation` group by outlet",
		as_dict=True,
	)
	dev_map = {r["outlet"]: r["count"] for r in deviation_counts}

	return [
		{
			"outlet": r["outlet"],
			"compliance": round(flt(r["compliance"])),
			"deviations": dev_map.get(r["outlet"], 0),
		}
		for r in compliance_rows
	]


def _dashboard_repeat_failures():
	"""The original brief's ">3 failures/month" threshold, adapted to the
	frontend's flatter {check_description, outlet, fail_count} shape
	(no month dimension) - counts total failures per check+outlet.
	"""
	return frappe.db.sql(
		"""
		select
			sci.check_description as check_description,
			sc.location as outlet,
			count(*) as fail_count
		from `tabShift Checklist Item` sci
		inner join `tabShift Checklist` sc on sc.name = sci.parent
		where sci.status = 'Not OK' and sc.docstatus = 1 and sc.location is not null
		group by sci.check_description, sc.location
		having count(*) > 3
		order by fail_count desc
		""",
		as_dict=True,
	)


def _dashboard_escalations():
	return {
		"open": frappe.db.count("Checklist Deviation", {"resolution_status": ["!=", "Closed"]}),
		"closed": frappe.db.count("Checklist Deviation", {"resolution_status": "Closed"}),
	}
