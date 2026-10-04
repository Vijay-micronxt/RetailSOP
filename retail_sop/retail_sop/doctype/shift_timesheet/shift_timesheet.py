# Copyright (c) 2026, Micronxt and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_time, getdate, time_diff_in_hours

# A flagged assumption, not a confirmed labor-law figure: generous enough
# to cover a legitimate double shift, tight enough to catch a fat-fingered
# check_in/check_out (e.g. AM/PM mixed up) that would otherwise silently
# log ~24 hours. Adjust if real usage needs a different ceiling.
MAX_SHIFT_HOURS = 16

# Another flagged assumption: how far back a self-service entry can
# backdate. Generous enough for "forgot to log yesterday", tight enough
# that a months-old entry gets a second look from whoever's approving it
# instead of sailing through silently.
MAX_BACKDATE_DAYS = 14

# Attendance statuses that mean the employee wasn't actually working that
# day - a Shift Timesheet claiming hours on top of one of these is a
# direct contradiction, not just an unusual combination.
NOT_WORKING_ATTENDANCE_STATUSES = {"Absent", "On Leave"}


class ShiftTimesheet(Document):
	def validate(self):
		self._lock_if_already_actioned()
		self._validate_date_bounds()
		self._compute_and_validate_hours()
		self._check_attendance_consistency()
		self._check_overlap()

	def _is_new_claim(self):
		"""True for a brand-new entry, or a resubmission
		(hr_api.resubmit_timesheet, flagged via self.flags.is_resubmission)
		- the two cases where the employee is actually asserting a (first
		or corrected) date/time claim that date-bounds/Attendance should
		judge. False for every other save, notably action_timesheet()'s
		own Open -> Approved/Rejected flip, which doesn't touch the claim
		at all - re-checking those rules there would make the outcome
		depend on how long the entry sat waiting for approval, not on
		whether it was valid when it was actually filed.
		"""
		return self.is_new() or self.flags.get("is_resubmission")

	def _lock_if_already_actioned(self):
		"""Once a Supervisor/Manager has approved or rejected an entry
		(hr_api.action_timesheet), nothing - including this doctype's own
		API surface, Desk, or any future caller - should be able to edit
		it further, with one exception: hr_api.resubmit_timesheet flipping
		a Rejected entry back to Open is the one allowed transition, so a
		corrected resubmission doesn't have to be filed as a whole new
		row. Checked against the DB's current value rather than
		get_doc_before_save() so this doesn't depend on how/when Frappe
		populates that cache; a plain read of "what's in the database
		right now, before this save" is unambiguous. The Open ->
		Approved/Rejected transition itself is unaffected either: at the
		moment action_timesheet() saves that change, the DB still has
		"Open".
		"""
		if self.is_new():
			return
		current_status = frappe.db.get_value("Shift Timesheet", self.name, "status")
		if not current_status or current_status == "Open":
			return
		if current_status == "Rejected" and self.status == "Open":
			return
		frappe.throw(_("This timesheet has already been actioned and can no longer be changed."))

	def _validate_date_bounds(self):
		if not (self._is_new_claim() and self.date):
			return

		today = getdate()
		entry_date = getdate(self.date)
		if entry_date > today:
			frappe.throw(_("You can't log a timesheet for a future date."))
		if (today - entry_date).days > MAX_BACKDATE_DAYS:
			frappe.throw(
				_("This date is more than {0} days in the past - double-check it's correct.").format(
					MAX_BACKDATE_DAYS
				)
			)

	def _compute_and_validate_hours(self):
		if not (self.check_in and self.check_out):
			return
		self.hours_worked = round(
			time_diff_in_hours(f"{self.date} {self.check_out}", f"{self.date} {self.check_in}"), 2
		)
		if self.hours_worked <= 0:
			frappe.throw(
				_(
					"Check-out must be after check-in. For a shift crossing midnight, log it as two "
					"separate entries (one ending at 23:59, one starting at 00:00)."
				)
			)
		if self.hours_worked > MAX_SHIFT_HOURS:
			frappe.throw(
				_("A single shift can't be longer than {0} hours - check your check-in/check-out times.")
				.format(MAX_SHIFT_HOURS)
			)

	def _check_attendance_consistency(self):
		"""Same _is_new_claim() scoping as _validate_date_bounds, and for
		the same reason: an Attendance record submitted *after* this
		timesheet already exists (Open) shouldn't retroactively block its
		later approval just because it happened to land before that save.
		"""
		if not (self._is_new_claim() and self.employee and self.date):
			return

		attendance_status = frappe.db.get_value(
			"Attendance",
			{"employee": self.employee, "attendance_date": self.date, "docstatus": 1},
			"status",
		)
		if attendance_status in NOT_WORKING_ATTENDANCE_STATUSES:
			frappe.throw(
				_('Attendance for {0} is marked "{1}" - can\'t log a shift for a day you weren\'t in.')
				.format(self.date, attendance_status)
			)

	def _check_overlap(self):
		"""Blocks two entries for the same employee/date whose check_in-
		check_out ranges overlap - the exact gap this was added to close
		(an employee could otherwise log any number of overlapping/
		duplicate shifts for one day). Doesn't block a second
		*non-overlapping* entry for the same day (e.g. a genuine split
		shift), and ignores Rejected entries so a corrected resubmission
		after a rejection isn't blocked by the mistake it's fixing.
		"""
		if not (self.employee and self.date and self.check_in and self.check_out):
			return

		self_start, self_end = get_time(self.check_in), get_time(self.check_out)
		others = frappe.get_all(
			"Shift Timesheet",
			filters={
				"employee": self.employee,
				"date": self.date,
				"name": ["!=", self.name or ""],
				"status": ["!=", "Rejected"],
			},
			fields=["name", "check_in", "check_out"],
		)
		for other in others:
			other_start, other_end = get_time(other.check_in), get_time(other.check_out)
			if self_start < other_end and other_start < self_end:
				frappe.throw(
					_(
						"This overlaps an existing timesheet entry ({0}: {1}-{2}) for the same day."
					).format(other.name, other.check_in, other.check_out)
				)
