import frappe
from frappe.utils import get_datetime, getdate, now_datetime, today


def mark_missed_checklists():
	"""Scheduler event (hourly): flip status to Missed, in the database
	field itself, for any unsubmitted Shift Checklist whose cutoff_time has
	passed - so Desk list views/filters/reports show it, not just the
	frontend API's live-computed status (retail_sop.api._computed_status,
	which already reflects this instantly and doesn't wait on this job).
	Submission is separately hard-blocked past cutoff regardless of whether
	this job has run yet - see ShiftChecklist.enforce_not_missed().
	"""
	candidates = frappe.get_all(
		"Shift Checklist",
		filters={"docstatus": 0, "cutoff_time": ["is", "set"], "status": ["!=", "Missed"]},
		fields=["name", "date", "cutoff_time"],
	)
	now = now_datetime()
	for row in candidates:
		if now > get_datetime(f"{row.date} {row.cutoff_time}"):
			frappe.db.set_value("Shift Checklist", row.name, "status", "Missed")
	if candidates:
		frappe.db.commit()


def create_daily_shift_checklists():
	"""Scheduler event (daily): create one Draft Shift Checklist per active
	Checklist Template that's due today, with items pre-populated from the
	template. A Daily-frequency template is due every day (original
	behavior, unchanged); a Weekly-frequency one is only due on its own
	configured weekly_day - see _is_template_due_today().
	"""
	template_names = frappe.get_all("Checklist Template", filters={"active": 1}, pluck="name")
	for template_name in template_names:
		try:
			_create_shift_checklist_from_template(template_name)
		except Exception:
			frappe.log_error(
				title=f"Failed to auto-create Shift Checklist from {template_name}",
				reference_doctype="Checklist Template",
				reference_name=template_name,
			)


def _is_template_due_today(template):
	if template.frequency != "Weekly":
		return True
	return getdate(today()).strftime("%A") == template.weekly_day


def _create_shift_checklist_from_template(template_name):
	template = frappe.get_doc("Checklist Template", template_name)
	if not _is_template_due_today(template):
		return

	# Avoid creating a duplicate Draft for the same template on the same day
	# if the scheduler is re-run.
	existing = frappe.db.exists(
		"Shift Checklist",
		{"checklist_template": template_name, "date": today(), "docstatus": ["!=", 2]},
	)
	if existing:
		return

	checklist = frappe.new_doc("Shift Checklist")
	checklist.naming_series = "EXO-CHK-.YYYY.-.####"
	checklist.date = today()
	checklist.shift_type = template.shift_type
	checklist.checklist_scope = template.checklist_scope
	checklist.location = template.location
	checklist.checklist_template = template.name
	checklist.cutoff_time = template.cutoff_time
	checklist.status = "Draft"
	checklist.workflow_state = "Draft"

	for template_item in template.items:
		checklist.append("items", {"template_item": template_item.name})

	checklist.insert(ignore_permissions=True)
