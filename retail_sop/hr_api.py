"""Attendance + leave request API, layered on top of Frappe HR's own
Employee/Attendance/Leave Application/Leave Type doctypes (the "hrms" app -
see hooks.py::required_apps) rather than reinventing them inside retail_sop.

Two audiences, per the actual use case:
  - Outlet/vendor floor staff: usually have no login of their own. A
    Supervisor/Manager marks their attendance for the day on their behalf
    (list_outlet_employees / get_attendance_for_date / mark_attendance),
    and can review any one employee's full history
    (get_employee_attendance_history / get_employee_leave_history -
    paginated, optionally bounded to a date range). Scoped to one outlet
    at a time via the Employee.outlet custom field (see
    fixtures/custom_field.json) - Employee itself has no such field
    natively.
  - This app's own users (Supervisor/Manager/Store Operator): self-service
    leave and timesheets, same as any Employee Self Service portal -
    apply_leave/get_my_leave_balance/get_my_leave_applications and
    submit_timesheet/get_my_timesheets - resolved via Employee.user_id
    matching frappe.session.user, same pattern as
    retail_sop.api.get_my_store_summary's Outlet.store_operator lookup.

Permission model matches the rest of this app: Food Court Supervisor/
Manager/Store Operator hold **no** direct doctype permission on Employee/
Attendance/Leave Application/Shift Timesheet (HRMS's own permission model
is built around HR Manager/HR User, which this app's roles aren't) - every
read/write here runs with ignore_permissions=True and this module's own
role checks are the only gate, exactly like retail_sop.api's
_check_staff_role.

Leave and timesheet approval in this app is flat, not per-employee-
assigned: any Food Court Supervisor or Manager can action any Open leave
application or timesheet (mirroring how any Manager can Verify any Shift
Checklist in api.py), rather than routing through
Employee.leave_approver's normal one-approver-per-employee chain. That
field still gets set on a new Leave Application (falling back to any Food
Court Manager if the employee's own record doesn't have one) purely
because HRMS's own form expects it to be populated - not to restrict who
may actually approve.

Shift Timesheet is this app's own lightweight doctype (not HRMS's real
Timesheet, which is built around Task/Project costing that doesn't apply
here) - just a shift hours log an employee fills in themselves
(check_in/check_out -> hours_worked, computed server-side in
ShiftTimesheet.validate) that a Supervisor or Manager approves or
rejects, same shape as the leave flow above.
"""

import frappe
from frappe import _
from frappe.utils import cint, getdate

from retail_sop.api import _check_auth, _check_staff_role

ATTENDANCE_STATUSES = {"Present", "Absent", "Half Day", "On Leave"}


def _get_my_employee():
	employee = frappe.db.get_value(
		"Employee", {"user_id": frappe.session.user, "status": "Active"}, "name"
	)
	if not employee:
		frappe.throw(_("Your account is not linked to an Employee record."), frappe.PermissionError)
	return employee


def _fallback_leave_approver():
	"""Employee.leave_approver, when set, is a specific person's whole
	job here - but it's still just a form field HRMS expects filled in
	when one isn't configured. Any Food Court Manager is a reasonable
	real value (see module docstring for why approval itself doesn't
	actually restrict to this particular person).
	"""
	return frappe.db.get_value("Has Role", {"role": "Food Court Manager"}, "parent")


# ---------------------------------- reads -----------------------------------


@frappe.whitelist()
def list_outlet_employees(outlet=None):
	"""Active Employees, optionally filtered to one outlet - the roster a
	Supervisor/Manager picks from when marking attendance.
	"""
	_check_auth()
	_check_staff_role()
	filters = {"status": "Active"}
	if outlet:
		filters["outlet"] = outlet
	return frappe.get_all(
		"Employee",
		filters=filters,
		fields=["name", "employee_name", "outlet", "designation"],
		order_by="employee_name",
		ignore_permissions=True,
	)


@frappe.whitelist()
def get_attendance_for_date(date=None, outlet=None):
	"""Each active employee (optionally filtered to one outlet) paired
	with their Attendance status for `date` (today if omitted), or None
	if nobody has marked it yet.
	"""
	_check_auth()
	_check_staff_role()
	date = getdate(date) if date else getdate()

	employees = list_outlet_employees(outlet)
	if not employees:
		return []

	marked = frappe.get_all(
		"Attendance",
		filters={"attendance_date": date, "docstatus": 1, "employee": ["in", [e.name for e in employees]]},
		fields=["employee", "status"],
		ignore_permissions=True,
	)
	status_by_employee = {row.employee: row.status for row in marked}

	return [
		{
			"employee": e.name,
			"employee_name": e.employee_name,
			"outlet": e.outlet,
			"designation": e.designation,
			"status": status_by_employee.get(e.name),
		}
		for e in employees
	]


@frappe.whitelist()
def get_leave_types():
	_check_auth()
	# Leave Type doesn't have a "disabled" field on every HRMS version (it
	# threw "Unknown column" on at least one real site) - only filter on it
	# when the installed version's doctype actually has the field, rather
	# than assuming a specific schema.
	filters = {"disabled": 0} if frappe.get_meta("Leave Type").has_field("disabled") else {}
	# ignore_permissions=True, same as every other call in this module -
	# Food Court roles hold zero native permission on Leave Type (or any
	# other HRMS doctype), so without it this silently returns [] instead
	# of throwing, and the Raise-leave form's type chips never populate.
	return frappe.get_all(
		"Leave Type", filters=filters, pluck="name", order_by="name", ignore_permissions=True
	)


@frappe.whitelist()
def get_my_leave_balance():
	"""allocated - taken, per Leave Type, for the calling user's own
	Employee record. Computed directly from Leave Allocation / Leave
	Application rather than any HRMS internal helper, so this doesn't
	depend on a version-specific function signature.
	"""
	_check_auth()
	employee = _get_my_employee()

	allocations = frappe.get_all(
		"Leave Allocation",
		filters={"employee": employee, "docstatus": 1},
		fields=["leave_type", "total_leaves_allocated"],
		ignore_permissions=True,
	)
	allocated_by_type = {}
	for row in allocations:
		allocated_by_type[row.leave_type] = allocated_by_type.get(row.leave_type, 0) + (
			row.total_leaves_allocated or 0
		)

	taken = frappe.get_all(
		"Leave Application",
		filters={"employee": employee, "status": "Approved", "docstatus": 1},
		fields=["leave_type", "total_leave_days"],
		ignore_permissions=True,
	)
	taken_by_type = {}
	for row in taken:
		taken_by_type[row.leave_type] = taken_by_type.get(row.leave_type, 0) + (
			row.total_leave_days or 0
		)

	leave_types = set(allocated_by_type) | set(taken_by_type)
	return [
		{
			"leave_type": lt,
			"allocated": allocated_by_type.get(lt, 0),
			"taken": taken_by_type.get(lt, 0),
			"balance": allocated_by_type.get(lt, 0) - taken_by_type.get(lt, 0),
		}
		for lt in sorted(leave_types)
	]


@frappe.whitelist()
def get_my_leave_applications():
	_check_auth()
	employee = _get_my_employee()
	return frappe.get_all(
		"Leave Application",
		filters={"employee": employee, "docstatus": ["!=", 2]},
		fields=["name", "leave_type", "from_date", "to_date", "total_leave_days", "status", "description"],
		order_by="from_date desc",
		ignore_permissions=True,
	)


@frappe.whitelist()
def get_pending_leave_approvals():
	"""Every Open leave application, for any Food Court Supervisor or
	Manager to action - see module docstring for why this is flat rather
	than routed to one assigned approver.
	"""
	_check_auth()
	roles = set(frappe.get_roles(frappe.session.user))
	if not roles & {"Food Court Supervisor", "Food Court Manager", "System Manager"}:
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	return frappe.get_all(
		"Leave Application",
		filters={"status": "Open", "docstatus": 1},
		fields=[
			"name",
			"employee",
			"employee_name",
			"leave_type",
			"from_date",
			"to_date",
			"total_leave_days",
			"description",
		],
		order_by="from_date asc",
		ignore_permissions=True,
	)


def _paginate(doctype, filters, fields, order_by, page, page_size):
	page = cint(page) or 1
	page_size = min(cint(page_size) or 20, 100)
	total = frappe.db.count(doctype, filters=filters)
	records = frappe.get_all(
		doctype,
		filters=filters,
		fields=fields,
		order_by=order_by,
		limit_start=(page - 1) * page_size,
		limit_page_length=page_size,
		ignore_permissions=True,
	)
	return {"records": records, "total": total, "page": page, "page_size": page_size}


def _date_range_filter(fieldname, from_date, to_date):
	"""[fieldname, operator, value] filter for an optional [from_date,
	to_date] window - either bound alone, both, or neither (no filter).
	"""
	filters = {}
	if from_date and to_date:
		filters[fieldname] = ["between", [getdate(from_date), getdate(to_date)]]
	elif from_date:
		filters[fieldname] = [">=", getdate(from_date)]
	elif to_date:
		filters[fieldname] = ["<=", getdate(to_date)]
	return filters


@frappe.whitelist()
def get_employee_attendance_history(employee, from_date=None, to_date=None, page=1, page_size=20):
	"""Paginated Attendance history for one employee (bounded to
	[from_date, to_date] on attendance_date when given), for a
	Supervisor/Manager reviewing that person's record - not self-service,
	see get_my_leave_applications for the caller's-own-record equivalent.
	"""
	_check_auth()
	_check_staff_role()
	if not employee:
		frappe.throw(_("employee is required."))

	filters = {
		"employee": employee,
		"docstatus": 1,
		**_date_range_filter("attendance_date", from_date, to_date),
	}
	return _paginate(
		"Attendance",
		filters,
		["name", "attendance_date", "status"],
		"attendance_date desc",
		page,
		page_size,
	)


@frappe.whitelist()
def get_employee_leave_history(employee, from_date=None, to_date=None, page=1, page_size=20):
	"""Paginated Leave Application history for one employee (bounded to
	[from_date, to_date] on from_date when given) - same Supervisor/
	Manager review use case as get_employee_attendance_history.
	"""
	_check_auth()
	_check_staff_role()
	if not employee:
		frappe.throw(_("employee is required."))

	filters = {
		"employee": employee,
		"docstatus": ["!=", 2],
		**_date_range_filter("from_date", from_date, to_date),
	}
	return _paginate(
		"Leave Application",
		filters,
		["name", "leave_type", "from_date", "to_date", "total_leave_days", "status", "description"],
		"from_date desc",
		page,
		page_size,
	)


# --------------------------------- writes -----------------------------------


@frappe.whitelist()
def mark_attendance(records, date=None):
	"""records: list of {"employee": ..., "status": ...}. `date` defaults
	to today - deliberately the server's own notion of "today"
	(getdate(), same as get_attendance_for_date's default), not whatever
	date a caller computes client-side. A browser computing "today" via
	something UTC-based (e.g. Date.toISOString()) can disagree with the
	server's local date near midnight, which would silently write against
	the wrong calendar day and disagree with what get_attendance_for_date
	then shows for "today" - so this endpoint doesn't trust a
	client-supplied date determination, only an explicit override.

	Skips (rather than errors out) any employee who already has a
	submitted Attendance for that date - re-marking a submitted day isn't
	supported here, only filling in what's still blank.
	"""
	_check_auth()
	_check_staff_role()

	if not records:
		frappe.throw(_("records is required."))

	date = getdate(date) if date else getdate()
	marked, skipped = [], []

	for record in records:
		employee = record.get("employee")
		status = record.get("status")
		if not employee or status not in ATTENDANCE_STATUSES:
			frappe.throw(_("Each record needs a valid employee and status."))

		if frappe.db.exists("Attendance", {"employee": employee, "attendance_date": date, "docstatus": 1}):
			skipped.append(employee)
			continue

		company = frappe.db.get_value("Employee", employee, "company")
		attendance = frappe.new_doc("Attendance")
		attendance.employee = employee
		attendance.attendance_date = date
		attendance.status = status
		attendance.company = company
		attendance.insert(ignore_permissions=True)
		attendance.submit()
		marked.append(employee)

	return {"marked": marked, "skipped": skipped}


@frappe.whitelist()
def apply_leave(leave_type, from_date, to_date, reason=None):
	_check_auth()
	if not (leave_type and from_date and to_date):
		frappe.throw(_("leave_type, from_date and to_date are all required."))

	employee = _get_my_employee()
	leave_approver = frappe.db.get_value("Employee", employee, "leave_approver") or (
		_fallback_leave_approver()
	)

	application = frappe.new_doc("Leave Application")
	application.employee = employee
	application.leave_type = leave_type
	application.from_date = from_date
	application.to_date = to_date
	application.description = reason
	if leave_approver:
		application.leave_approver = leave_approver
	# HRMS's own validate() enforces leave balance/holiday/overlap rules -
	# never re-implement that here, just let it throw if the request is
	# actually invalid.
	application.insert(ignore_permissions=True)
	application.submit()

	return {
		"name": application.name,
		"status": application.status,
		"total_leave_days": application.total_leave_days,
	}


@frappe.whitelist()
def action_leave_application(name, approve):
	_check_auth()
	roles = set(frappe.get_roles(frappe.session.user))
	if not roles & {"Food Court Supervisor", "Food Court Manager", "System Manager"}:
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	application = frappe.get_doc("Leave Application", name)
	if application.status != "Open":
		frappe.throw(_("This leave application has already been actioned."))

	application.status = "Approved" if cint(approve) else "Rejected"
	application.save(ignore_permissions=True)

	return {"name": application.name, "status": application.status}


# ------------------------------- timesheets ----------------------------


@frappe.whitelist()
def get_my_timesheets():
	_check_auth()
	employee = _get_my_employee()
	return frappe.get_all(
		"Shift Timesheet",
		filters={"employee": employee},
		fields=["name", "date", "check_in", "check_out", "hours_worked", "status", "remarks"],
		order_by="date desc",
		ignore_permissions=True,
	)


@frappe.whitelist()
def submit_timesheet(date, check_in, check_out, remarks=None):
	_check_auth()
	if not (date and check_in and check_out):
		frappe.throw(_("date, check_in and check_out are all required."))

	employee = _get_my_employee()
	timesheet = frappe.new_doc("Shift Timesheet")
	timesheet.employee = employee
	timesheet.date = date
	timesheet.check_in = check_in
	timesheet.check_out = check_out
	timesheet.remarks = remarks
	timesheet.status = "Open"
	timesheet.insert(ignore_permissions=True)

	return {
		"name": timesheet.name,
		"status": timesheet.status,
		"hours_worked": timesheet.hours_worked,
	}


@frappe.whitelist()
def get_pending_timesheet_approvals():
	"""Every Open Shift Timesheet, for any Food Court Supervisor or
	Manager to action - flat, same as get_pending_leave_approvals.
	"""
	_check_auth()
	roles = set(frappe.get_roles(frappe.session.user))
	if not roles & {"Food Court Supervisor", "Food Court Manager", "System Manager"}:
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	return frappe.get_all(
		"Shift Timesheet",
		filters={"status": "Open"},
		fields=[
			"name",
			"employee",
			"employee_name",
			"date",
			"check_in",
			"check_out",
			"hours_worked",
			"remarks",
		],
		order_by="date asc",
		ignore_permissions=True,
	)


@frappe.whitelist()
def action_timesheet(name, approve):
	_check_auth()
	roles = set(frappe.get_roles(frappe.session.user))
	if not roles & {"Food Court Supervisor", "Food Court Manager", "System Manager"}:
		frappe.throw(_("Not permitted."), frappe.PermissionError)

	timesheet = frappe.get_doc("Shift Timesheet", name)
	if timesheet.status != "Open":
		frappe.throw(_("This timesheet has already been actioned."))

	timesheet.status = "Approved" if cint(approve) else "Rejected"
	timesheet.save(ignore_permissions=True)

	return {"name": timesheet.name, "status": timesheet.status}
