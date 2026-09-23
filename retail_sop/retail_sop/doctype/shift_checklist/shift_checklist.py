# Copyright (c) 2026, Micronxt and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, get_datetime, getdate, now_datetime, nowdate


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
		self.sync_fields_from_template()
		self.enforce_workflow_state_transition()
		self.apply_numeric_range_checks()
		self.compute_summary()

		if self.docstatus == 1:
			self.enforce_not_missed()
			self.enforce_submit_rules()
			self.enforce_completion_confirmed()

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
	# cutoff_time, checklist_scope and location are always re-derived from
	# the linked Checklist Template here, every save - never trusted from
	# whatever the client (Desk form or an API payload) sent in. This is
	# what actually stops a stray/mismatched value (fields left at their
	# defaults on manual creation, a Duplicate action copying an old doc's
	# values, or any other path that bypasses tasks.py's own copy) from
	# sticking - the template is the true source of truth for all three,
	# full stop, checked fresh every time. Without this, a manually-created
	# checklist could end up with e.g. checklist_scope="Outlet" while
	# linked to a Food Court template, which then fails
	# _check_checklist_write_access() in api.py for everyone.
	# ------------------------------------------------------------------
	def sync_fields_from_template(self):
		if self.checklist_template:
			template = frappe.db.get_value(
				"Checklist Template",
				self.checklist_template,
				["cutoff_time", "checklist_scope", "location"],
				as_dict=True,
			)
			self.cutoff_time = template.cutoff_time
			self.checklist_scope = template.checklist_scope
			self.location = template.location
		else:
			self.cutoff_time = None

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

		transition = (before.workflow_state, self.workflow_state)
		user_roles = set(frappe.get_roles(frappe.session.user))
		if "System Manager" in user_roles:
			return

		if transition == ("Draft", "Submitted"):
			# Who may submit depends on checklist_scope, same split as
			# api.py::_check_checklist_write_access() - Food Court Supervisor
			# for a Food Court-scope checklist, Store Operator only for their
			# own outlet's Outlet-scope one. Not imported from api.py to avoid
			# a circular import (api.py already imports from this module).
			if self.checklist_scope == "Food Court" and "Food Court Supervisor" in user_roles:
				return
			if self.checklist_scope == "Outlet" and "Store Operator" in user_roles:
				my_outlet = frappe.db.get_value(
					"Outlet", {"store_operator": frappe.session.user}, "outlet_name"
				)
				if self.location == my_outlet:
					return
			frappe.throw(_("You are not permitted to submit this Shift Checklist."))

		if transition == ("Submitted", "Verified"):
			if "Food Court Manager" in user_roles:
				return
			frappe.throw(_("You need the Food Court Manager role to verify this Shift Checklist."))

		frappe.throw(
			_("Invalid workflow transition from {0} to {1}.").format(
				before.workflow_state, self.workflow_state
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
	# Cutoff enforcement - a checklist whose Checklist Template set a
	# cutoff_time cannot be submitted after that time has passed, even if
	# every row is otherwise complete. Once missed, it stays missed - the
	# record itself is never deleted, it just can never move past Draft.
	# ------------------------------------------------------------------
	def enforce_not_missed(self):
		if not self.cutoff_time:
			return
		if now_datetime() > get_datetime(f"{self.date} {self.cutoff_time}"):
			frappe.throw(
				_(
					"The cutoff time for this checklist ({0}) has passed - it is marked Missed and can no longer be submitted."
				).format(self.cutoff_time)
			)

	# ------------------------------------------------------------------
	# Sign-off - "I confirm that I have personally completed the above
	# checks and the information submitted is correct" (repeated on every
	# checklist type in the source sheet). A paper-trail/accountability
	# requirement, not a data-quality check - who submitted and when is
	# already recorded by Frappe itself (owner/creation); this just makes
	# that confirmation an explicit, required step rather than implicit in
	# clicking Submit.
	# ------------------------------------------------------------------
	def enforce_completion_confirmed(self):
		if not self.completion_confirmed:
			frappe.throw(
				_(
					"Please confirm you have personally completed this checklist and the "
					"information submitted is correct before submitting."
				)
			)

	# ------------------------------------------------------------------
	# Submit-time blocking rules
	# ------------------------------------------------------------------
	def enforce_submit_rules(self):
		blocking_rows = self._compute_blocking_rows()
		if not blocking_rows:
			return

		# The structured `rows` list is what retail_sop.api.submit_checklist
		# reshapes into the frontend's per-row error display. A Desk-native
		# Submit only ever shows str(exception) though, so the message
		# itself also needs to name the actual checks - a bare count here
		# left Desk users with no way to tell which rows to go fix.
		preview = "\n".join(
			f"- Sr {r['sr_no']} ({r['check_description']}): {r['message']}" for r in blocking_rows[:5]
		)
		if len(blocking_rows) > 5:
			preview += _("\n...and {0} more.").format(len(blocking_rows) - 5)

		raise ShiftChecklistValidationError(
			_("Cannot submit Shift Checklist: {0} row(s) failing validation.\n{1}").format(
				len(blocking_rows), preview
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
					self._blocking_row(row, _("This mandatory check has not been marked yet."))
				)
				continue

			if template_item.requires_photo and row.status == "Not OK" and not row.attachment:
				blocking_rows.append(
					self._blocking_row(row, _("A photo is required when this check is marked Not OK."))
				)
				continue

			# A mandatory row with a status set can still be incomplete for its
			# input type - e.g. marked OK on a Numeric check with no reading
			# entered. Mirrors the frontend's own isRowComplete check.
			if template_item.is_mandatory:
				incomplete = (
					(template_item.input_type == "Numeric" and not row.reading)
					or (template_item.input_type == "Text" and not row.remarks)
					or (template_item.input_type == "Photo" and not row.attachment)
				)
				if incomplete:
					blocking_rows.append(
						self._blocking_row(row, _("Please complete the entry for this check."))
					)

		return blocking_rows

	def _blocking_row(self, row, message):
		return {
			"row": row.name,
			"idx": row.idx,
			"sr_no": row.sr_no,
			"check_description": row.check_description,
			"message": message,
		}

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
			deviation.severity = template_item.severity or "Medium"
			deviation.issue = _("Auto-raised: '{0}' failed during {1}.").format(
				row.check_description, self.name
			)
			# Carry over the row's own evidence photo, if one was attached -
			# an auto-raised deviation with a required-photo item behind it
			# otherwise ends up with no evidence at all.
			deviation.photo = row.attachment
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
