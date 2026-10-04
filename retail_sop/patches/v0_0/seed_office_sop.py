"""Seed checklist content for sites configured with
retail_sop_domain = "office" (see retail_sop/domain.py) - the office/
workplace-facilities counterpart to seed_my_break_sop.py's food-court
content. Mirrors that patch's structure and conventions exactly (same
Tick/Numeric/Text helpers, same CRITICAL = requires_photo + escalate_on_fail
+ escalate_to Food Court Manager - the role's internal name doesn't change
per domain, only its display label does), just with office-appropriate
sections and checks instead of kitchen/food-safety ones.

checklist_scope="Outlet" templates are created once per active Outlet (an
"Outlet" record stands in for one office location here); checklist_scope=
"Food Court" templates are the organization-wide counterpart, created once
with no Location - exactly the same scope split as the store domain, just
relabelled for display (see api.get_domain_info / domain.LABELS).
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


def _text(category, description, **overrides):
	item = {
		"check_description": description,
		"category": category,
		"input_type": "Text",
		"is_mandatory": 0,
	}
	item.update(overrides)
	return item


# --------------------------- Office Opening Checklist ---------------------------

OFFICE_OPENING_ITEMS = [
	*[
		_tick("Workspace Readiness", d)
		for d in [
			"Main entrance unlocked and accessible",
			"Reception/lobby area clean and tidy",
			"Workstations and desks clean",
			"Meeting rooms clean and ready",
			"Floors clean and dry",
			"Lighting working in all areas",
			"AC/HVAC switched on and functioning",
			"No unpleasant odour noticed",
		]
	],
	_tick("Safety & Access", "Fire exits unobstructed", **CRITICAL),
	_tick("Safety & Access", "Access control/badge system functioning", **CRITICAL),
	*[
		_tick("Safety & Access", d)
		for d in [
			"Fire extinguishers in place and accessible",
			"Emergency lighting working",
			"CCTV cameras operational",
			"Visitor log/register ready",
		]
	],
	_tick("IT & Equipment", "Wi-Fi/network connectivity working", **CRITICAL),
	*[
		_tick("IT & Equipment", d)
		for d in [
			"Printers/scanners switched on and have paper",
			"Projectors/AV equipment in meeting rooms working",
			"Phone/intercom systems working",
			"Workstation monitors/peripherals checked",
		]
	],
	*[
		_tick("Pantry & Facilities", d)
		for d in [
			"Drinking water available",
			"Pantry/kitchenette clean and stocked",
			"Coffee/tea machine working",
			"Restrooms clean and stocked with supplies",
			"Handwash soap/sanitiser available",
		]
	],
	*[
		_tick("Staff Readiness", d)
		for d in [
			"Security/housekeeping staff present",
			"Daily briefing/handover completed",
			"No pending maintenance issue from previous day",
		]
	],
]


# --------------------------- Office Closing Checklist ---------------------------

OFFICE_CLOSING_ITEMS = [
	_tick("Workspace Shutdown", "No confidential documents left unattended", **CRITICAL),
	*[
		_tick("Workspace Shutdown", d)
		for d in [
			"All workstations/desks cleared and tidy",
			"Meeting rooms reset and tidy",
			"Unused lights switched off",
			"AC/HVAC switched off or set to night mode",
		]
	],
	_tick("Security & Safety", "All doors/windows locked", **CRITICAL),
	*[
		_tick("Security & Safety", d)
		for d in [
			"Access control system armed",
			"CCTV recording confirmed active",
			"Fire exits checked clear",
			"Security staff briefed for the night",
		]
	],
	_tick("Equipment Shutdown", "Server room/network equipment checked and secured", **CRITICAL),
	*[
		_tick("Equipment Shutdown", d)
		for d in [
			"Non-essential electrical equipment switched off",
			"Printers/scanners powered off",
			"Projectors/AV equipment powered off",
			"Pantry equipment switched off",
		]
	],
	*[
		_tick("Cleaning & Waste", d)
		for d in [
			"Waste bins emptied",
			"Pantry/kitchenette cleaned",
			"Restrooms cleaned and stocked for next day",
			"Floors cleaned",
			"Recycling segregated as per policy",
		]
	],
]


# --------------------------- Office Weekly Facility Checklist ---------------------------

OFFICE_WEEKLY_ITEMS = [
	*[
		_tick("Facility Condition", d)
		for d in [
			"Furniture condition checked",
			"Carpets/flooring condition checked",
			"Ceiling/wall condition checked",
			"Plumbing/leakage issues checked",
		]
	],
	_tick("Facility Condition", "No pest activity observed", **CRITICAL),
	_tick("Safety & Compliance", "Fire extinguisher inspection/service date checked", **CRITICAL),
	_tick("Safety & Compliance", "Electrical wiring/sockets checked for damage", **CRITICAL),
	*[
		_tick("Safety & Compliance", d)
		for d in [
			"Fire alarm system tested",
			"Emergency contact numbers displayed and current",
			"First-aid kit available and stocked",
			"Evacuation plan displayed and visible",
		]
	],
	*[
		_tick("IT Infrastructure", d)
		for d in [
			"Network/server room temperature checked",
			"UPS/backup power tested",
			"IT asset inventory reviewed",
			"Software licence compliance reviewed",
		]
	],
	*[
		_tick("Housekeeping Standards", d)
		for d in [
			"Deep cleaning of common areas completed",
			"Pantry deep-cleaned",
			"Restroom supplies inventory checked",
			"Vendor/contractor compliance reviewed",
		]
	],
]


# --------------------------- Organization Daily Review Checklist ---------------------------

ORG_DAILY_ITEMS = [
	_tick(
		"Overall Office Status",
		"Critical issues reported by locations reviewed",
		**CRITICAL,
	),
	_tick(
		"Overall Office Status",
		"No location has an unresolved critical safety issue",
		**CRITICAL,
	),
	*[
		_tick("Overall Office Status", d)
		for d in [
			"All office locations' opening checklists completed",
			"Any location reporting a delayed opening",
		]
	],
	*[
		_tick("Safety & Security", d)
		for d in [
			"No unresolved security incident across locations",
			"Access control systems functioning at all locations",
			"CCTV systems operational at all locations",
		]
	],
	*[
		_tick("Staff & Facilities", d)
		for d in [
			"Staff attendance reviewed across locations",
			"Common facility services (power/water/internet) operational",
			"Any location reporting equipment breakdown",
		]
	],
]


# --------------------------- Organization Weekly Audit Checklist ---------------------------

ORG_WEEKLY_ITEMS = [
	_tick("Compliance Review", "Fire safety compliance confirmed across locations", **CRITICAL),
	_tick(
		"Compliance Review", "Statutory licences/certificates valid at all locations", **CRITICAL
	),
	_tick("Compliance Review", "Any compliance issue escalated and tracked"),
	*[
		_tick("Facility & Maintenance", d)
		for d in [
			"Pending maintenance issues reviewed across locations",
			"Vendor/contractor performance reviewed",
			"IT infrastructure issues reviewed",
		]
	],
	*[
		_tick("Staff & Operations", d)
		for d in [
			"Staff grooming/conduct standards reviewed",
			"Weekly incidents/complaints reviewed",
			"Training requirements identified",
		]
	],
]


TEMPLATES = [
	{
		"template_name": "Office Opening Checklist",
		"shift_type": "Pre-Opening",
		"checklist_scope": "Outlet",
		"frequency": "Daily",
		"items": OFFICE_OPENING_ITEMS,
	},
	{
		"template_name": "Office Closing Checklist",
		"shift_type": "Closing",
		"checklist_scope": "Outlet",
		"frequency": "Daily",
		"items": OFFICE_CLOSING_ITEMS,
	},
	{
		"template_name": "Office Weekly Facility Checklist",
		"shift_type": "Weekly Audit",
		"checklist_scope": "Outlet",
		"frequency": "Weekly",
		"weekly_day": "Monday",
		"items": OFFICE_WEEKLY_ITEMS,
	},
	{
		"template_name": "Organization Daily Review Checklist",
		"shift_type": "Pre-Opening",
		"checklist_scope": "Food Court",
		"frequency": "Daily",
		"items": ORG_DAILY_ITEMS,
	},
	{
		"template_name": "Organization Weekly Audit Checklist",
		"shift_type": "Weekly Audit",
		"checklist_scope": "Food Court",
		"frequency": "Weekly",
		"weekly_day": "Monday",
		"items": ORG_WEEKLY_ITEMS,
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

	if get_domain() != "office":
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
