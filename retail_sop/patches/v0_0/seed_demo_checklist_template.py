import frappe

# NOTE: this 12-check list is a PLACEHOLDER. The user is expected to paste
# the real reference checklist separately - swap DEMO_ITEMS below for the
# real list and re-run this patch (or update the "Pre-Opening Demo" record
# directly) once it's provided.
DEMO_ITEMS = [
	{
		"sr_no": 1,
		"check_description": "Entrance, seating area and floor are clean and free of debris",
		"category": "Common Area",
		"input_type": "Tick",
		"is_mandatory": 1,
	},
	{
		"sr_no": 2,
		"check_description": "Tables and chairs wiped down and arranged",
		"category": "Common Area",
		"input_type": "Tick",
		"is_mandatory": 1,
	},
	{
		"sr_no": 3,
		"check_description": "Handwashing stations stocked with soap and paper towels",
		"category": "Hygiene",
		"input_type": "Tick",
		"is_mandatory": 1,
		"requires_photo": 1,
		"escalate_on_fail": 1,
		"escalate_to_type": "Role",
		"escalate_to": "Food Court Manager",
	},
	{
		"sr_no": 4,
		"check_description": "Staff wearing gloves and hairnets at food prep stations",
		"category": "Hygiene",
		"input_type": "Tick",
		"is_mandatory": 1,
	},
	{
		"sr_no": 5,
		"check_description": "Refrigerator temperature within safe range",
		"category": "Hygiene",
		"input_type": "Numeric",
		"standard": "1-4 deg C",
		"min_value": 1,
		"max_value": 4,
		"is_mandatory": 1,
		"escalate_on_fail": 1,
		"escalate_to_type": "Role",
		"escalate_to": "Food Court Manager",
	},
	{
		"sr_no": 6,
		"check_description": "Vendor food licence displayed and valid",
		"category": "Vendor Compliance",
		"input_type": "Tick",
		"is_mandatory": 1,
		"vendor_specific": 1,
	},
	{
		"sr_no": 7,
		"check_description": "Vendor staff wearing valid ID badges",
		"category": "Vendor Compliance",
		"input_type": "Tick",
		"is_mandatory": 1,
		"vendor_specific": 1,
	},
	{
		"sr_no": 8,
		"check_description": "POS/billing system operational at all counters",
		"category": "Revenue",
		"input_type": "Tick",
		"is_mandatory": 1,
		"escalate_on_fail": 1,
		"escalate_to_type": "Role",
		"escalate_to": "Food Court Manager",
	},
	{
		"sr_no": 9,
		"check_description": "Opening cash float counted and matches register",
		"category": "Revenue",
		"input_type": "Numeric",
		"standard": "As per float sheet",
		"is_mandatory": 1,
	},
	{
		"sr_no": 10,
		"check_description": "Fire extinguishers in place and within inspection date",
		"category": "Safety",
		"input_type": "Tick",
		"is_mandatory": 1,
		"requires_photo": 1,
		"escalate_on_fail": 1,
		"escalate_to_type": "Role",
		"escalate_to": "Food Court Manager",
	},
	{
		"sr_no": 11,
		"check_description": "Emergency exits unobstructed and signage visible",
		"category": "Safety",
		"input_type": "Tick",
		"is_mandatory": 1,
	},
	{
		"sr_no": 12,
		"check_description": "First aid kit stocked and accessible",
		"category": "Safety",
		"input_type": "Tick",
		"is_mandatory": 1,
	},
]


def execute():
	frappe.reload_doc("retail_sop", "doctype", "outlet")
	frappe.reload_doc("retail_sop", "doctype", "checklist_template_item")
	frappe.reload_doc("retail_sop", "doctype", "checklist_template")

	if not frappe.db.exists("Outlet", "Common Area"):
		frappe.get_doc({"doctype": "Outlet", "outlet_name": "Common Area", "active": 1}).insert(
			ignore_permissions=True
		)

	if frappe.db.exists("Checklist Template", "Pre-Opening Demo"):
		return

	template = frappe.new_doc("Checklist Template")
	template.template_name = "Pre-Opening Demo"
	template.shift_type = "Pre-Opening"
	template.location = "Common Area"
	template.active = 1

	for item in DEMO_ITEMS:
		template.append("items", item)

	template.insert(ignore_permissions=True)
