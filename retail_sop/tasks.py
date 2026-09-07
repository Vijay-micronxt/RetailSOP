import frappe
from frappe.utils import today


def create_daily_shift_checklists():
	"""Scheduler event (daily): create one Draft Shift Checklist per active
	Checklist Template, with items pre-populated from the template.
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


def _create_shift_checklist_from_template(template_name):
	# Avoid creating a duplicate Draft for the same template on the same day
	# if the scheduler is re-run.
	existing = frappe.db.exists(
		"Shift Checklist",
		{"checklist_template": template_name, "date": today(), "docstatus": ["!=", 2]},
	)
	if existing:
		return

	template = frappe.get_doc("Checklist Template", template_name)

	checklist = frappe.new_doc("Shift Checklist")
	checklist.naming_series = "EXO-CHK-.YYYY.-.####"
	checklist.date = today()
	checklist.shift_type = template.shift_type
	checklist.location = template.location
	checklist.checklist_template = template.name
	checklist.status = "Draft"
	checklist.workflow_state = "Draft"

	for template_item in template.items:
		checklist.append("items", {"template_item": template_item.name})

	checklist.insert(ignore_permissions=True)
