"""Seed checklist content for sites configured with
retail_sop_domain = "facility" (see retail_sop/domain.py) - the generic
facility/building-management counterpart to seed_my_break_sop.py's food-
court content and seed_office_sop.py's office content. Same structure and
conventions as both: same Tick/Text helpers, same CRITICAL =
requires_photo + escalate_on_fail + escalate_to Food Court Manager (the
role's internal name doesn't change per domain, only its display label
does), just with building/maintenance-appropriate sections and checks.

checklist_scope="Outlet" templates are created once per active Outlet (an
"Outlet" record stands in for one building/facility here); checklist_scope=
"Food Court" templates are the campus-wide counterpart, created once with
no Location - the same scope split as the other domains, just relabelled
for display (see api.get_domain_info / domain.LABELS).
"""

import frappe

CRITICAL = {
	"requires_photo": 1,
	"escalate_on_fail": 1,
	"escalate_to_type": "Role",
	"escalate_to": "Food Court Manager",
}


def _tick(category, description, **overrides):
	item = {
		"check_description": description,
		"category": category,
		"input_type": "Tick",
		"is_mandatory": 1,
	}
	item.update(overrides)
	return item


# --------------------------- Facility Opening Round ---------------------------

FACILITY_OPENING_ITEMS = [
	*[
		_tick("Building Readiness", d)
		for d in [
			"Main entrance/gates unlocked and accessible",
			"Lobby/reception areas clean",
			"Lighting working in common areas",
			"Signage/way-finding intact",
		]
	],
	_tick("Safety Systems", "Fire alarm panel shows normal status", **CRITICAL),
	_tick("Safety Systems", "Emergency exits unobstructed", **CRITICAL),
	*[
		_tick("Safety Systems", d)
		for d in [
			"Fire extinguishers in place and accessible",
			"CCTV systems operational",
			"Security personnel on duty",
		]
	],
	_tick("Mechanical & Electrical", "Elevators/lifts operational", **CRITICAL),
	*[
		_tick("Mechanical & Electrical", d)
		for d in [
			"HVAC systems running normally",
			"Water supply/pumps functioning",
			"Backup generator/UPS status checked",
			"No unusual noise/vibration from equipment",
		]
	],
	*[
		_tick("Grounds & Common Areas", d)
		for d in [
			"Parking areas clean and organised",
			"Landscaping/grounds maintained",
			"Waste collection points clear",
			"Restrooms clean and stocked",
		]
	],
]


# --------------------------- Facility Closing Round ---------------------------

FACILITY_CLOSING_ITEMS = [
	_tick("Building Shutdown", "All entry/exit points locked as per procedure", **CRITICAL),
	_tick("Building Shutdown", "Non-essential lighting switched off"),
	*[
		_tick("Security & Safety", d)
		for d in [
			"Security personnel briefed for the night",
			"CCTV recording confirmed active",
			"Fire exits checked clear",
		]
	],
	_tick("Mechanical & Electrical", "Electrical panels checked and secured", **CRITICAL),
	*[
		_tick("Mechanical & Electrical", d)
		for d in [
			"HVAC set to night mode/switched off as applicable",
			"Elevators/lifts set to night mode if applicable",
			"No water leakage observed",
		]
	],
	*[
		_tick("Cleaning & Waste", d)
		for d in [
			"Waste bins emptied",
			"Common areas cleaned",
			"Restrooms cleaned and restocked",
		]
	],
]


# --------------------------- Facility Weekly Maintenance & Safety ---------------------------

FACILITY_WEEKLY_ITEMS = [
	_tick("Structural & Mechanical", "Elevators/lifts inspection/service date checked", **CRITICAL),
	_tick("Structural & Mechanical", "Electrical systems inspected", **CRITICAL),
	*[
		_tick("Structural & Mechanical", d)
		for d in [
			"HVAC filters/maintenance checked",
			"Plumbing systems checked for leaks",
			"Structural issues (cracks/damage) reported",
		]
	],
	_tick("Safety & Compliance", "Fire extinguishers service/inspection date checked", **CRITICAL),
	_tick("Safety & Compliance", "Statutory compliance certificates valid", **CRITICAL),
	*[
		_tick("Safety & Compliance", d)
		for d in [
			"Fire alarm system tested",
			"Emergency evacuation plan displayed",
			"First-aid kits available and stocked",
		]
	],
	_tick("Grounds & Vendor Management", "Pest control treatment completed as scheduled", **CRITICAL),
	*[
		_tick("Grounds & Vendor Management", d)
		for d in [
			"Landscaping/grounds maintenance reviewed",
			"Vendor/contractor compliance reviewed",
			"Waste management contractor performance reviewed",
		]
	],
]


# --------------------------- Campus Daily Review ---------------------------

CAMPUS_DAILY_ITEMS = [
	_tick("Overall Campus Status", "Critical issues reported by buildings reviewed", **CRITICAL),
	_tick(
		"Overall Campus Status", "No building has an unresolved critical safety issue", **CRITICAL
	),
	_tick("Overall Campus Status", "All buildings' opening checks completed"),
	*[
		_tick("Safety & Security", d)
		for d in [
			"No unresolved security incident across buildings",
			"CCTV systems operational across buildings",
			"Access control functioning across buildings",
		]
	],
	*[
		_tick("Operations", d)
		for d in [
			"Staff attendance reviewed",
			"Common utilities (power/water) operational",
			"Equipment breakdowns reviewed",
		]
	],
]


# --------------------------- Campus Weekly Safety Audit ---------------------------

CAMPUS_WEEKLY_ITEMS = [
	_tick("Compliance Review", "Fire safety compliance confirmed across buildings", **CRITICAL),
	_tick("Compliance Review", "Statutory certificates valid across buildings", **CRITICAL),
	_tick("Compliance Review", "Compliance issues escalated and tracked"),
	*[
		_tick("Maintenance & Vendor", d)
		for d in [
			"Pending maintenance reviewed across buildings",
			"Vendor/contractor performance reviewed",
			"Equipment AMC/service schedules reviewed",
		]
	],
	*[
		_tick("Incidents & Training", d)
		for d in [
			"Weekly incidents/accidents reviewed",
			"Safety training requirements identified",
			"Near-miss reports reviewed",
		]
	],
]


TEMPLATES = [
	{
		"template_name": "Facility Opening Round",
		"shift_type": "Pre-Opening",
		"checklist_scope": "Outlet",
		"frequency": "Daily",
		"items": FACILITY_OPENING_ITEMS,
	},
	{
		"template_name": "Facility Closing Round",
		"shift_type": "Closing",
		"checklist_scope": "Outlet",
		"frequency": "Daily",
		"items": FACILITY_CLOSING_ITEMS,
	},
	{
		"template_name": "Facility Weekly Maintenance & Safety Checklist",
		"shift_type": "Weekly Audit",
		"checklist_scope": "Outlet",
		"frequency": "Weekly",
		"weekly_day": "Monday",
		"items": FACILITY_WEEKLY_ITEMS,
	},
	{
		"template_name": "Campus Daily Review Checklist",
		"shift_type": "Pre-Opening",
		"checklist_scope": "Food Court",
		"frequency": "Daily",
		"items": CAMPUS_DAILY_ITEMS,
	},
	{
		"template_name": "Campus Weekly Safety Audit Checklist",
		"shift_type": "Weekly Audit",
		"checklist_scope": "Food Court",
		"frequency": "Weekly",
		"weekly_day": "Monday",
		"items": CAMPUS_WEEKLY_ITEMS,
	},
]


def _ensure_categories(items):
	existing = set(frappe.get_all("Checklist Category", pluck="name"))
	for item in items:
		category = item["category"]
		if category not in existing:
			frappe.get_doc(
				{"doctype": "Checklist Category", "category_name": category, "active": 1}
			).insert(ignore_permissions=True)
			existing.add(category)


def _append_items(template_doc, items):
	for sr_no, item in enumerate(items, start=1):
		template_doc.append("items", {**item, "sr_no": sr_no})


def _create_template(template_name, location, spec):
	if frappe.db.exists("Checklist Template", template_name):
		return

	doc = frappe.new_doc("Checklist Template")
	doc.template_name = template_name
	doc.shift_type = spec["shift_type"]
	doc.checklist_scope = spec["checklist_scope"]
	doc.frequency = spec["frequency"]
	if spec.get("weekly_day"):
		doc.weekly_day = spec["weekly_day"]
	if location:
		doc.location = location
	doc.active = 1

	_append_items(doc, spec["items"])
	doc.insert(ignore_permissions=True)


def execute():
	from retail_sop.domain import get_domain

	if get_domain() != "facility":
		return

	frappe.reload_doc("retail_sop", "doctype", "checklist_category")
	frappe.reload_doc("retail_sop", "doctype", "checklist_template_item")
	frappe.reload_doc("retail_sop", "doctype", "checklist_template")
	frappe.reload_doc("retail_sop", "doctype", "outlet")

	# Same placeholder demo template seed_demo_checklist_template.py
	# creates on every site, regardless of domain - retire it the same
	# way seed_my_break_sop.py does for the store domain, so it stops
	# being auto-created daily once this domain's real content exists.
	if frappe.db.exists("Checklist Template", "Pre-Opening Demo"):
		frappe.db.set_value("Checklist Template", "Pre-Opening Demo", "active", 0)

	for spec in TEMPLATES:
		_ensure_categories(spec["items"])

		if spec["checklist_scope"] == "Food Court":
			_create_template(spec["template_name"], None, spec)
			continue

		outlets = frappe.get_all("Outlet", filters={"active": 1}, pluck="name")
		for outlet in outlets:
			_create_template(f"{spec['template_name']} - {outlet}", outlet, spec)
