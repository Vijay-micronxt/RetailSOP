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
from frappe.utils import cint, flt, get_datetime, now_datetime, nowtime, today

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


def _computed_status(doc):
	"""Maps our docstatus/workflow_state onto the frontend's ChecklistStatus
	union (Draft/In Progress/Submitted/Verified/Escalated) - the doctype's
	own `status` field is kept for internal/Desk bookkeeping only and is
	not the source of truth for what the API reports.
	"""
	if doc.docstatus == 2:
		return "Draft"
	if doc.docstatus == 0:
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
				["input_type", "min_value", "max_value", "is_mandatory", "requires_photo"],
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
		"location": doc.location,
		"supervisor": doc.supervisor,
		"status": _computed_status(doc),
		"compliance_score": doc.compliance_score,
		"total_checks": doc.total_checks,
		"failed_checks": doc.failed_checks,
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
def get_today_checklists(date=None, outlet=None, limit=None, offset=None):
	_check_auth()
	_check_staff_role()
	conditions = [["date", "=", date or today()], ["docstatus", "!=", 2]]
	if outlet and outlet != "All":
		conditions.append(["location", "=", outlet])
	names = _get_checklist_names(conditions, "creation desc", limit, offset)
	return [_serialize_checklist(frappe.get_doc("Shift Checklist", n)) for n in names]


@frappe.whitelist()
def get_checklist(name):
	_check_auth()
	_check_staff_role()
	if not frappe.db.exists("Shift Checklist", name):
		return None
	return _serialize_checklist(frappe.get_doc("Shift Checklist", name))


@frappe.whitelist()
def get_history(from_date=None, to_date=None, workflow_state=None, outlet=None, limit=50, offset=0):
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
	names = _get_checklist_names(conditions, "date desc", limit, offset)
	return [_serialize_checklist(frappe.get_doc("Shift Checklist", n)) for n in names]


@frappe.whitelist()
def get_verification_queue(outlet=None, from_date=None, to_date=None, limit=50, offset=0):
	_check_auth()
	_check_staff_role()
	conditions = [["docstatus", "=", 1], ["workflow_state", "!=", "Verified"]]
	if outlet and outlet != "All":
		conditions.append(["location", "=", outlet])
	if from_date:
		conditions.append(["date", ">=", from_date])
	if to_date:
		conditions.append(["date", "<=", to_date])
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
def get_my_store_checklists(date=None):
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

	outlet = frappe.db.get_value("Outlet", {"store_operator": frappe.session.user}, "outlet_name")
	if not outlet:
		frappe.throw(_("Your account is not linked to a store."), frappe.PermissionError)

	names = frappe.get_all(
		"Shift Checklist",
		filters={"location": outlet, "date": date or today(), "docstatus": ["!=", 2]},
		pluck="name",
		order_by="creation desc",
		ignore_permissions=True,
	)
	return [_serialize_checklist(frappe.get_doc("Shift Checklist", n)) for n in names]


@frappe.whitelist()
def get_my_store_history(from_date=None, to_date=None, limit=50, offset=0):
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
	names = _get_checklist_names(conditions, "date desc", limit, offset)
	return [_serialize_checklist(frappe.get_doc("Shift Checklist", n)) for n in names]


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


# --------------------------------- writes ------------------------------------


@frappe.whitelist()
def save_checklist_row(checklist_name, sr_no, status=None, reading=None, remarks=None, attachment=None):
	_check_auth()

	doc = frappe.get_doc("Shift Checklist", checklist_name)
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
def submit_checklist(name):
	"""Validation (mandatory/photo/completeness rules) lives entirely in
	ShiftChecklist.validate() - this just calls submit() and reshapes
	whatever it raised into the frontend's SubmitResponse shape.
	"""
	_check_auth()

	doc = frappe.get_doc("Shift Checklist", name)
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
def create_deviation(outlet, category, severity, issue, action_taken, photo=None):
	_check_auth()

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
	if severity == "Critical":
		# Frontend default was a placeholder "Area Manager" string; using
		# the real Food Court Manager role instead so this also lines up
		# with the Critical-deviation email notification (see
		# checklist_deviation.py / the Notification fixture).
		doc.escalated_to = "Food Court Manager"

	doc.insert()
	return _serialize_deviation(doc)


@frappe.whitelist()
def update_deviation_status(name, resolution_status):
	_check_auth()

	doc = frappe.get_doc("Checklist Deviation", name)
	doc.resolution_status = resolution_status
	if resolution_status == "Closed":
		doc.closed_by = frappe.session.user
		doc.closed_on = today()
	else:
		doc.closed_by = None
		doc.closed_on = None
	doc.save()
	return _serialize_deviation(doc)


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
		where docstatus = 1 and date >= date_sub(curdate(), interval 6 month)
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
		where docstatus = 1
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
		where sci.status = 'Not OK' and sc.docstatus = 1
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
