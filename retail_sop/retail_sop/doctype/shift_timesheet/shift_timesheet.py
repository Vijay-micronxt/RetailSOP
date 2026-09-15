# Copyright (c) 2026, Micronxt and contributors
# For license information, please see license.txt

from frappe.model.document import Document
from frappe.utils import time_diff_in_hours


class ShiftTimesheet(Document):
	def validate(self):
		if self.check_in and self.check_out:
			self.hours_worked = round(
				time_diff_in_hours(f"{self.date} {self.check_out}", f"{self.date} {self.check_in}"), 2
			)
