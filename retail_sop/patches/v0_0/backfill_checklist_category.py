import frappe

# The "category" field on Checklist Template Item / Shift Checklist Item /
# Checklist Deviation moved from a fixed Select list to a Link against the
# new Checklist Category doctype - Food Court Managers now manage the
# category list themselves in the Desk (needed since this app is
# white-labelled across food courts with different category sets), and
# retail_sop.api.list_categories() reads from that doctype instead of a
# hardcoded options string.
#
# A Link field is still just a string column under the hood, so this
# doesn't rewrite any existing data - it only backfills a Checklist
# Category record for every distinct category value already present on
# any site (the demo seed's Common Area/Hygiene/Vendor Compliance/Revenue/
# Safety, plus anything a live site has already been using), so existing
# rows keep resolving to a valid Link target instead of failing validation
# the next time they're opened and saved.


def execute():
	frappe.reload_doc("retail_sop", "doctype", "checklist_category")
	frappe.reload_doc("retail_sop", "doctype", "checklist_template_item")
	frappe.reload_doc("retail_sop", "doctype", "shift_checklist_item")
	frappe.reload_doc("retail_sop", "doctype", "checklist_deviation")

	existing = set(frappe.get_all("Checklist Category", pluck="name"))

	values = set()
	for doctype, field, table in (
		("Checklist Template Item", "category", "tabChecklist Template Item"),
		("Shift Checklist Item", "category", "tabShift Checklist Item"),
		("Checklist Deviation", "category", "tabChecklist Deviation"),
	):
		for row in frappe.db.sql(
			f"select distinct `{field}` as category from `{table}` where `{field}` is not null and `{field}` != ''",
			as_dict=True,
		):
			values.add(row.category)

	for value in sorted(values - existing):
		frappe.get_doc(
			{"doctype": "Checklist Category", "category_name": value, "active": 1}
		).insert(ignore_permissions=True)
