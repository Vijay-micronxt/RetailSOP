# Copyright (c) 2026, Micronxt and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class ChecklistTemplate(Document):
	def validate(self):
		"""checklist_scope decides what Location means, not the other way
		around - keep the two from drifting out of sync with each other
		(an Outlet-scope template with no outlet, or a Food-Court-scope one
		that still names one) rather than leaving it to whoever's filling
		the form to notice.
		"""
		if self.checklist_scope == "Outlet" and not self.location:
			frappe.throw(_("Location is required when Checklist Scope is Outlet."))
		if self.checklist_scope == "Food Court" and self.location:
			frappe.throw(_("Location must be blank when Checklist Scope is Food Court."))
