"""Whitelisted REST API surface consumed by the Lovable.dev frontend.

Auth: assumes Frappe's built-in API key/secret (token) authentication,
enforced by the framework before a request reaches these handlers (i.e.
Authorization: token <api_key>:<api_secret>). `_check_auth` is kept as a
single choke point so the strategy can be swapped later (e.g. a custom
header, JWT) without touching every method.

All responses are plain dict/list JSON - no Frappe Document objects or
internal metadata are returned directly.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime, today

from retail_sop.retail_sop.doctype.shift_checklist.shift_checklist import (
	ShiftChecklistValidationError,
)


def _check_auth():
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication required"), frappe.AuthenticationError)


@frappe.whitelist()
def get_todays_checklists(supervisor=None):
	"""List today's Shift Checklists, optionally filtered by supervisor."""
	_check_auth()

	filters = {"date": today()}
	if supervisor:
		filters["supervisor"] = supervisor

	return frappe.get_all(
		"Shift Checklist",
		filters=filters,
		fields=[
			"name",
			"date",
			"shift_type",
			"location",
			"supervisor",
			"checklist_template",
			"start_time",
			"end_time",
			"status",
			"workflow_state",
			"docstatus",
			"compliance_score",
			"total_checks",
			"failed_checks",
		],
		order_by="creation desc",
	)


@frappe.whitelist()
def get_checklist_detail(name):
	"""Full checklist with items, each row carrying its template context
	(standard, thresholds, mandatory/photo flags) so the frontend doesn't
	need a second round trip per row.
	"""
	_check_auth()

	doc = frappe.get_doc("Shift Checklist", name)

	items = []
	for row in doc.items:
		template = {}
		if row.template_item:
			template_item = frappe.get_cached_doc("Checklist Template Item", row.template_item)
			template = {
				"input_type": template_item.input_type,
				"standard": template_item.standard,
				"min_value": template_item.min_value,
				"max_value": template_item.max_value,
				"is_mandatory": bool(template_item.is_mandatory),
				"requires_photo": bool(template_item.requires_photo),
				"escalate_on_fail": bool(template_item.escalate_on_fail),
				"vendor_specific": bool(template_item.vendor_specific),
			}

		items.append(
			{
				"row_name": row.name,
				"sr_no": row.sr_no,
				"check_description": row.check_description,
				"category": row.category,
				"standard": row.standard,
				"status": row.status,
				"reading": row.reading,
				"checked_at": row.checked_at,
				"checked_by": row.checked_by,
				"remarks": row.remarks,
				"attachment": row.attachment,
				"vendor": row.vendor,
				"template": template,
			}
		)

	return {
		"name": doc.name,
		"date": doc.date,
		"shift_type": doc.shift_type,
		"location": doc.location,
		"supervisor": doc.supervisor,
		"checklist_template": doc.checklist_template,
		"start_time": doc.start_time,
		"end_time": doc.end_time,
		"status": doc.status,
		"workflow_state": doc.workflow_state,
		"docstatus": doc.docstatus,
		"compliance_score": doc.compliance_score,
		"total_checks": doc.total_checks,
		"failed_checks": doc.failed_checks,
		"items": items,
	}


@frappe.whitelist()
def update_check_item(checklist, row_name, status=None, reading=None, remarks=None):
	"""Update one Shift Checklist Item row. Stamps checked_at/checked_by
	server-side and returns the live compliance_score/failed_checks so the
	frontend can show progress without re-fetching the whole document.
	"""
	_check_auth()

	doc = frappe.get_doc("Shift Checklist", checklist)
	if doc.docstatus != 0:
		frappe.throw(_("Cannot update items on a submitted or cancelled Shift Checklist."))

	row = next((r for r in doc.items if r.name == row_name), None)
	if not row:
		frappe.throw(_("Row {0} not found in {1}.").format(row_name, checklist))

	if status is not None:
		row.status = status
	if reading is not None:
		row.reading = reading
	if remarks is not None:
		row.remarks = remarks

	row.checked_at = now_datetime()
	row.checked_by = frappe.session.user

	doc.save()

	updated_row = next(r for r in doc.items if r.name == row_name)
	return {
		"row_name": updated_row.name,
		"status": updated_row.status,
		"reading": updated_row.reading,
		"checked_at": updated_row.checked_at,
		"checked_by": updated_row.checked_by,
		"compliance_score": doc.compliance_score,
		"total_checks": doc.total_checks,
		"failed_checks": doc.failed_checks,
	}


@frappe.whitelist()
def submit_checklist(name):
	"""Submit a Shift Checklist. Validation (mandatory/photo/numeric-range
	rules) lives entirely in ShiftChecklist.validate() - this just calls
	submit() and reshapes whatever it raised.
	"""
	_check_auth()

	doc = frappe.get_doc("Shift Checklist", name)
	try:
		doc.submit()
	except ShiftChecklistValidationError as e:
		return {
			"success": False,
			"message": str(e),
			"blocking_rows": e.rows,
		}

	return {
		"success": True,
		"name": doc.name,
		"workflow_state": doc.workflow_state,
		"compliance_score": doc.compliance_score,
		"total_checks": doc.total_checks,
		"failed_checks": doc.failed_checks,
	}


@frappe.whitelist()
def create_deviation(
	date=None,
	time=None,
	shift_checklist=None,
	outlet=None,
	category=None,
	severity=None,
	issue=None,
	action_taken=None,
	photo=None,
	escalated_to=None,
):
	"""Manual/ad-hoc deviation raise."""
	_check_auth()

	if not issue:
		frappe.throw(_("Issue description is required."))

	doc = frappe.new_doc("Checklist Deviation")
	doc.date = date or today()
	doc.time = time
	doc.shift_checklist = shift_checklist
	doc.outlet = outlet
	doc.category = category
	doc.severity = severity or "Medium"
	doc.issue = issue
	doc.action_taken = action_taken
	doc.photo = photo
	doc.escalated_to = escalated_to
	doc.insert()

	return {"name": doc.name, "resolution_status": doc.resolution_status}


@frappe.whitelist()
def update_deviation_status(name, resolution_status, closed_by=None):
	_check_auth()

	doc = frappe.get_doc("Checklist Deviation", name)
	doc.resolution_status = resolution_status
	if resolution_status == "Closed":
		doc.closed_by = closed_by or frappe.session.user
		doc.closed_on = today()
	doc.save()

	return {
		"name": doc.name,
		"resolution_status": doc.resolution_status,
		"closed_by": doc.closed_by,
		"closed_on": doc.closed_on,
	}


@frappe.whitelist()
def get_deviations(outlet=None, resolution_status=None):
	"""For the Kanban board."""
	_check_auth()

	filters = {}
	if outlet:
		filters["outlet"] = outlet
	if resolution_status:
		filters["resolution_status"] = resolution_status

	return frappe.get_all(
		"Checklist Deviation",
		filters=filters,
		fields=[
			"name",
			"date",
			"time",
			"shift_checklist",
			"outlet",
			"category",
			"severity",
			"issue",
			"action_taken",
			"escalated_to",
			"resolution_status",
			"closed_by",
			"closed_on",
			"docstatus",
		],
		order_by="date desc, creation desc",
	)


@frappe.whitelist()
def get_dashboard_data(report_type, from_date, to_date, outlet=None):
	"""Single entry point for dashboard/report data.

	report_type is one of:
	  - compliance_trend               compliance % by outlet & month
	  - deviations_by_outlet_category  deviation counts by outlet & category
	  - open_vs_closed                 open vs closed deviation counts
	  - vendor_scorecard               per-vendor pass/fail compliance %
	  - repeat_failures                same check failing >3x/month, same outlet

	The exact shape of each report_type is a proposed/assumed contract
	(the brief asked to confirm this) - see the docstring on each
	_report_* helper below for its return shape, and adjust freely once
	the frontend's actual needs are known.
	"""
	_check_auth()

	handlers = {
		"compliance_trend": _report_compliance_trend,
		"deviations_by_outlet_category": _report_deviations_by_outlet_category,
		"open_vs_closed": _report_open_vs_closed,
		"vendor_scorecard": _report_vendor_scorecard,
		"repeat_failures": _report_repeat_failures,
	}

	handler = handlers.get(report_type)
	if not handler:
		frappe.throw(
			_("Unknown report_type '{0}'. Valid options: {1}").format(
				report_type, ", ".join(handlers.keys())
			)
		)

	return handler(from_date, to_date, outlet)


def _report_compliance_trend(from_date, to_date, outlet=None):
	"""Returns {"report_type": ..., "data": [{outlet, month, avg_compliance}]}
	one row per outlet per calendar month, averaged over submitted Shift
	Checklists in range.
	"""
	conditions = ["docstatus = 1", "date between %(from_date)s and %(to_date)s"]
	params = {"from_date": from_date, "to_date": to_date}
	if outlet:
		conditions.append("location = %(outlet)s")
		params["outlet"] = outlet
	where = " and ".join(conditions)

	data = frappe.db.sql(
		f"""
		select
			location as outlet,
			date_format(date, '%%Y-%%m') as month,
			avg(compliance_score) as avg_compliance
		from `tabShift Checklist`
		where {where}
		group by location, date_format(date, '%%Y-%%m')
		order by month
		""",
		params,
		as_dict=True,
	)
	return {"report_type": "compliance_trend", "data": data}


def _report_deviations_by_outlet_category(from_date, to_date, outlet=None):
	"""Returns {"report_type": ..., "data": [{outlet, category, count}]}."""
	conditions = ["date between %(from_date)s and %(to_date)s"]
	params = {"from_date": from_date, "to_date": to_date}
	if outlet:
		conditions.append("outlet = %(outlet)s")
		params["outlet"] = outlet
	where = " and ".join(conditions)

	data = frappe.db.sql(
		f"""
		select outlet, category, count(*) as count
		from `tabChecklist Deviation`
		where {where}
		group by outlet, category
		order by outlet, category
		""",
		params,
		as_dict=True,
	)
	return {"report_type": "deviations_by_outlet_category", "data": data}


def _report_open_vs_closed(from_date, to_date, outlet=None):
	"""Returns {"report_type": ..., "open": n, "closed": n,
	"by_status": [{resolution_status, count}]}.
	"""
	conditions = ["date between %(from_date)s and %(to_date)s"]
	params = {"from_date": from_date, "to_date": to_date}
	if outlet:
		conditions.append("outlet = %(outlet)s")
		params["outlet"] = outlet
	where = " and ".join(conditions)

	by_status = frappe.db.sql(
		f"""
		select resolution_status, count(*) as count
		from `tabChecklist Deviation`
		where {where}
		group by resolution_status
		""",
		params,
		as_dict=True,
	)
	closed = sum(row["count"] for row in by_status if row["resolution_status"] == "Closed")
	open_count = sum(row["count"] for row in by_status if row["resolution_status"] != "Closed")

	return {
		"report_type": "open_vs_closed",
		"open": open_count,
		"closed": closed,
		"by_status": by_status,
	}


def _report_vendor_scorecard(from_date, to_date, outlet=None):
	"""Returns {"report_type": ..., "data": [{vendor, total_checks,
	failed_checks, compliance_pct}]} for Shift Checklist Item rows with a
	vendor set, from submitted Shift Checklists in range.
	"""
	conditions = [
		"sci.vendor is not null",
		"sci.vendor != ''",
		"sc.date between %(from_date)s and %(to_date)s",
		"sc.docstatus = 1",
	]
	params = {"from_date": from_date, "to_date": to_date}
	if outlet:
		conditions.append("sc.location = %(outlet)s")
		params["outlet"] = outlet
	where = " and ".join(conditions)

	data = frappe.db.sql(
		f"""
		select
			sci.vendor as vendor,
			count(*) as total_checks,
			sum(case when sci.status = 'Not OK' then 1 else 0 end) as failed_checks
		from `tabShift Checklist Item` sci
		inner join `tabShift Checklist` sc on sc.name = sci.parent
		where {where}
		group by sci.vendor
		order by failed_checks desc
		""",
		params,
		as_dict=True,
	)
	for row in data:
		row["compliance_pct"] = (
			round(100 * (row["total_checks"] - row["failed_checks"]) / row["total_checks"], 2)
			if row["total_checks"]
			else 0
		)

	return {"report_type": "vendor_scorecard", "data": data}


def _report_repeat_failures(from_date, to_date, outlet=None):
	"""Returns {"report_type": ..., "data": [{outlet, check_description,
	month, failure_count}]} for checks that failed more than 3 times in the
	same outlet in the same calendar month, from submitted Shift Checklists
	in range.
	"""
	conditions = [
		"sci.status = 'Not OK'",
		"sc.date between %(from_date)s and %(to_date)s",
		"sc.docstatus = 1",
	]
	params = {"from_date": from_date, "to_date": to_date}
	if outlet:
		conditions.append("sc.location = %(outlet)s")
		params["outlet"] = outlet
	where = " and ".join(conditions)

	data = frappe.db.sql(
		f"""
		select
			sc.location as outlet,
			sci.check_description as check_description,
			date_format(sc.date, '%%Y-%%m') as month,
			count(*) as failure_count
		from `tabShift Checklist Item` sci
		inner join `tabShift Checklist` sc on sc.name = sci.parent
		where {where}
		group by sc.location, sci.check_description, date_format(sc.date, '%%Y-%%m')
		having count(*) > 3
		order by failure_count desc
		""",
		params,
		as_dict=True,
	)
	return {"report_type": "repeat_failures", "data": data}
