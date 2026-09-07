# Copyright (c) 2026, Micronxt and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class ChecklistDeviation(Document):
	def after_insert(self):
		# "Creation" here means insert, not submit - a Critical deviation is
		# operationally urgent and managers should be alerted immediately,
		# before anyone gets around to submitting the record.
		if self.severity == "Critical":
			notify_food_court_managers(self)


def notify_food_court_managers(deviation):
	"""Email channel notification to the Food Court Manager role.

	The primary delivery path is the "Critical Checklist Deviation Alert"
	Notification doctype record shipped as a fixture (Settings >
	Notification), which is the mechanism named in the brief. This
	function is a direct-email backstop so the alert still goes out even
	if that fixture didn't import cleanly on a given site/version - it is
	intentionally a plain frappe.sendmail call, not a second business-logic
	implementation of "should this notify".
	"""
	recipients = frappe.get_all(
		"Has Role",
		filters={"role": "Food Court Manager", "parenttype": "User"},
		pluck="parent",
	)
	recipients = [
		r for r in recipients if r not in ("Administrator", "Guest") and frappe.db.get_value("User", r, "enabled")
	]
	if not recipients:
		return

	frappe.sendmail(
		recipients=recipients,
		subject=_("Critical Deviation Raised: {0}").format(deviation.name),
		message=_(
			"A Critical severity deviation has been raised.<br><br>"
			"<b>Outlet:</b> {0}<br>"
			"<b>Category:</b> {1}<br>"
			"<b>Issue:</b> {2}<br>"
			"<b>Shift Checklist:</b> {3}<br>"
		).format(
			deviation.outlet or "",
			deviation.category or "",
			deviation.issue or "",
			deviation.shift_checklist or "",
		),
		reference_doctype=deviation.doctype,
		reference_name=deviation.name,
	)
