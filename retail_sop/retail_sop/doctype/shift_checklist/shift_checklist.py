# Copyright (c) 2026, Micronxt and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, now_datetime, nowdate


class ShiftChecklistValidationError(frappe.ValidationError):
	"""Raised by ShiftChecklist.validate() when the checklist cannot be
	submitted. Carries a structured list of the offending rows so callers
	(notably retail_sop.api.submit_checklist) can reshape it into a
	frontend-friendly response without re-running the validation logic
	themselves — this class, and validate() below, are the single source
	of truth for mandatory/photo/numeric-range rules.
	"""

	def __init__(self, message, rows=None):
		super().__init__(message)
		self.rows = rows or []


class ShiftChecklist(Document):
	def validate(self):
		self.validate_date_not_backdated()
		self.enforce_workflow_state_transition()
		self.apply_numeric_range_checks()
		self.compute_summary()

		if self.docstatus == 1:
			self.enforce_submit_rules()

	def on_submit(self):
		if self.workflow_state == "Draft":
			# Doctype was submitted without going through the configured
			# workflow (e.g. desk "Submit" button bypassing the workflow
			# action) - keep workflow_state in sync.
			self.db_set("workflow_state", "Submitted")
		self.create_deviations_for_failures()

	# ------------------------------------------------------------------
	# Date immutability / anti-backdating
	# ------------------------------------------------------------------
	def validate_date_not_backdated(self):
		if self.is_new():
			if self.date and getdate(self.date) < getdate(nowdate()):
				frappe.throw(_("Shift Checklist date cannot be in the past."))
			return

		before = self.get_doc_before_save()
		if before and before.date and self.date and getdate(before.date) != getdate(self.date):
			frappe.throw(_("Date cannot be changed once the Shift Checklist has been created."))

	# ------------------------------------------------------------------
	# Workflow transition guard (backstop for the declarative Workflow
	# config shipped as a fixture - keeps the rule enforced even if the
	# Workflow record is edited/removed on a given site).
	# ------------------------------------------------------------------
	def enforce_workflow_state_transition(self):
		if self.is_new():
			return

		before = self.get_doc_before_save()
		if not before or before.workflow_state == self.workflow_state:
			return

		allowed_transitions = {
			("Draft", "Submitted"): "Food Court Supervisor",
			("Submitted", "Verified"): "Food Court Manager",
		}
		required_role = allowed_transitions.get((before.workflow_state, self.workflow_state))
		if not required_role:
			frappe.throw(
				_("Invalid workflow transition from {0} to {1}.").format(
					before.workflow_state, self.workflow_state
				)
			)

		user_roles = frappe.get_roles(frappe.session.user)
		if required_role not in user_roles and "System Manager" not in user_roles:
			frappe.throw(
				_("You need the {0} role to move this Shift Checklist to {1}.").format(
					required_role, self.workflow_state
				)
			)

	# ------------------------------------------------------------------
	# Numeric range validation
	# ------------------------------------------------------------------
	def apply_numeric_range_checks(self):
		for row in self.items:
			template_item = self._get_template_item(row)
			if not template_item or template_item.input_type != "Numeric":
				continue
			if row.reading in (None, ""):
				continue

			try:
				value = flt(row.reading)
			except (TypeError, ValueError):
				continue

			min_value = flt(template_item.min_value)
			max_value = flt(template_item.max_value)

			# Treat 0/0 as "no range configured" for this check.
			if min_value == 0 and max_value == 0:
				continue

			if value < min_value or value > max_value:
				row.status = "Not OK"

	# ------------------------------------------------------------------
	# Compliance score / counters
	# ------------------------------------------------------------------
	def compute_summary(self):
		self.total_checks = len(self.items)
		self.failed_checks = len([row for row in self.items if row.status == "Not OK"])

		# NA rows are excluded from the compliance % denominator - they are
		# not applicable to this shift and shouldn't count against it.
		applicable = [row for row in self.items if row.status and row.status != "NA"]
		ok_count = len([row for row in applicable if row.status == "OK"])
		self.compliance_score = flt((ok_count / len(applicable)) * 100, 2) if applicable else 0.0

	# ------------------------------------------------------------------
	# Submit-time blocking rules
	# ------------------------------------------------------------------
	def enforce_submit_rules(self):
		blocking_rows = self._compute_blocking_rows()
		if blocking_rows:
			raise ShiftChecklistValidationError(
				_("Cannot submit Shift Checklist: {0} row(s) failing validation.").format(
					len(blocking_rows)
				),
				rows=blocking_rows,
			)

	def _compute_blocking_rows(self):
		blocking_rows = []
		for row in self.items:
			template_item = self._get_template_item(row)
			if not template_item:
				continue

			if template_item.is_mandatory and not row.status:
				blocking_rows.append(
					{
						"row": row.name,
						"idx": row.idx,
						"sr_no": row.sr_no,
						"check_description": row.check_description,
						"message": _("Mandatory check has no status."),
					}
				)
				continue

			if template_item.requires_photo and row.status == "Not OK" and not row.attachment:
				blocking_rows.append(
					{
						"row": row.name,
						"idx": row.idx,
						"sr_no": row.sr_no,
						"check_description": row.check_description,
						"message": _("Photo required when marked Not OK."),
					}
				)

		return blocking_rows

	# ------------------------------------------------------------------
	# Escalation on submit
	# ------------------------------------------------------------------
	def create_deviations_for_failures(self):
		for row in self.items:
			if row.status != "Not OK":
				continue

			template_item = self._get_template_item(row)
			if not template_item or not template_item.escalate_on_fail:
				continue

			deviation = frappe.new_doc("Checklist Deviation")
			deviation.date = self.date
			deviation.time = (row.checked_at or now_datetime()).time()
			deviation.shift_checklist = self.name
			deviation.outlet = self.location
			deviation.category = row.category or template_item.category
			# Default severity for auto-raised deviations. Not specified by
			# the brief - assumed "Medium"; adjust here if a different
			# default (or per-category default) is wanted.
			deviation.severity = "Medium"
			deviation.issue = _("Auto-raised: '{0}' failed during {1}.").format(
				row.check_description, self.name
			)
			if template_item.escalate_to_type == "User" and template_item.escalate_to:
				deviation.escalated_to = template_item.escalate_to
			elif template_item.escalate_to_type == "Role" and template_item.escalate_to:
				deviation.escalated_to = template_item.escalate_to

			deviation.insert(ignore_permissions=True)

	# ------------------------------------------------------------------
	# Helpers
	# ------------------------------------------------------------------
	def _get_template_item(self, row):
		if not row.template_item:
			return None
		return frappe.get_cached_doc("Checklist Template Item", row.template_item)


@frappe.whitelist()
def get_template_items(checklist_template):
	"""Desk UI convenience: return a Checklist Template's item rows so the
	client script can populate a Shift Checklist's items table without
	saving first (see public/js/shift_checklist.js).

	The normal creation path is the daily scheduler (tasks.py), which sets
	`template_item` on each row itself as it builds the document
	server-side. This exists for the manual-creation path in Desk, where
	sr_no/check_description/category/standard are otherwise unreachable -
	they're read-only fetch_from fields with nothing to fetch from until a
	row's template_item is set to something.
	"""
	if not checklist_template:
		frappe.throw(_("checklist_template is required."))

	return frappe.get_all(
		"Checklist Template Item",
		filters={"parent": checklist_template, "parenttype": "Checklist Template"},
		fields=["name", "sr_no", "check_description", "category", "standard"],
		order_by="idx",
	)
