import frappe

# The sheet's own Issue Reporting rule - "If any answer is NO, the manager
# must enter: Issue / Photo: Upload / ..." (QSR-Opening Sec 10, repeated on
# every checklist type) - applies to every item, not just the ~19 flagged
# CRITICAL during the initial content import (seed_my_break_sop.py). That
# script now sets requires_photo=1 on every item it creates going forward;
# this patch backfills the same onto whatever Checklist Template Item rows
# already exist on a site from before this change.


def execute():
	frappe.reload_doc("retail_sop", "doctype", "checklist_template_item")

	frappe.db.sql("update `tabChecklist Template Item` set requires_photo = 1 where requires_photo != 1")
	frappe.db.commit()
