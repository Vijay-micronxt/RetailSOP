"""Seeds the real "My Break Food Court Daily Operation SOP" checklist
content, replacing the placeholder demo template from
seed_demo_checklist_template.py (that patch's own comment already said
"swap DEMO_ITEMS for the real list... once it's provided" - it now has
been, transcribed from the source workbook the user shared).

Role/scope mapping agreed in conversation (source sheet terminology on
the left, this app's real roles on the right):
  - QSR (single-outlet daily/weekly checks)      -> Store Operator
  - FC-Manager (whole-food-court daily/weekly)   -> Food Court Supervisor
  - "Operations Manager" (escalation target)     -> Food Court Manager

So QSR-* templates below are checklist_scope="Outlet" and get created
once per active Outlet (the same content for every outlet - the sheet
doesn't vary it per outlet); FC-Manager-* templates are
checklist_scope="Food Court", created once each with no Location.

What's deliberately NOT imported as checklist rows, and why:
  - Per-outlet roster/status tables (FC-Manager Opening's "Outlet Opening
    Status", Closing's "Outlet Closing Status", Weekly's "Outlet
    Scorecard") - these get auto-derived from each outlet's own
    submitted QSR checklists instead of manually re-entered; see
    api.py::get_outlet_closing_status/get_outlet_scorecard.
  - The Weekly "Licence Expiry Tracker" and "Weekly Action Plan" (open
    issues) tables - licence-with-expiry tracking and a standalone
    action-item tracker are both genuinely new sub-features beyond a
    checklist row (the latter significantly overlaps what Checklist
    Deviation already does); out of scope for this content-import pass,
    flagged here as a known follow-up rather than force-fit into a
    Tick/Numeric/Text checklist item.
  - Meta/boilerplate rows: section intros ("Purpose: ..."), the
    "Manager Submission"/"Final Manager Declaration" signature blocks
    (Outlet/Manager/Date/Time, a final confirmation tick), and
    "Final Status" dropdown summaries (Ready to Open / Critical Issue
    Reported / etc.) - none of these are a check point, they're framing
    or a whole-checklist-level declaration already implied by
    submitting the checklist itself.
  - FC-Manager Weekly's trailing "How I would structure this on your
    website" section - notes to whoever authored the source sheet, not
    checklist content.
  - "Issue Reporting" sections describing what happens on a "No" answer
    (raise an issue, upload a photo, notify the Operations Manager) -
    this is exactly what escalate_on_fail + requires_photo already do
    automatically (see shift_checklist.py::create_deviations_for_failures),
    not a separate row to fill in.

Which items are marked requires_photo=1 + escalate_on_fail=1
(escalate_to Food Court Manager) is a curated subset representative of
what the sheet calls out as critical (e.g. QSR-Opening's own example:
"if the manager selects 'No' for refrigerator working, 'No' for food
safety, or 'No' for POS/payment working... create an action item for
the Operations Manager") - flagged as an editorial judgment call, not
an exhaustive mapping of every "No" the source sheet's prose might
imply; easy to extend via the Desk once real usage shows what else
should escalate.
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


def _numeric(category, description, standard=None, **overrides):
	item = {
		"check_description": description,
		"category": category,
		"input_type": "Numeric",
		"is_mandatory": 1,
	}
	if standard:
		item["standard"] = standard
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


# --------------------------- QSR-Opening Check List ---------------------------

QSR_OPENING_ITEMS = [
	*[
		_tick("Kitchen & Food Preparation", d)
		for d in [
			"Kitchen floor is clean and dry",
			"Work tables are clean and sanitised",
			"Cooking equipment is clean",
			"Gas/electrical connections checked and safe",
			"Exhaust/hood is working",
			"Hand-wash area is clean",
			"Handwash soap is available",
			"Paper towels/hand-drying facility available",
			"Cleaning chemicals are stored separately from food",
		]
	],
	_tick("Kitchen & Food Preparation", "No expired or damaged food found", **CRITICAL),
	*[
		_tick("Raw Material & Food Safety", d)
		for d in [
			"All raw materials are properly stored",
			"FIFO/FEFO is followed",
			"Vegetables and fruits are fresh",
			"Milk and dairy products checked",
			"Frozen products are properly frozen",
		]
	],
	_tick("Raw Material & Food Safety", "Refrigerator is working", **CRITICAL),
	_tick("Raw Material & Food Safety", "Freezer is working", **CRITICAL),
	*[
		_tick("Raw Material & Food Safety", d)
		for d in [
			"Refrigerator temperature recorded",
			"Freezer temperature recorded",
			"Opened products are covered and labelled",
			"Preparation containers are clean",
			"Food products are protected from contamination",
		]
	],
	_numeric("Raw Material & Food Safety", "Chiller temperature", standard="deg C"),
	_numeric("Raw Material & Food Safety", "Freezer temperature", standard="deg C"),
	*[
		_tick("Staff Hygiene & Readiness", d)
		for d in [
			"All scheduled staff have reported",
			"Staff attendance completed",
			"Clean uniform worn",
			"Hairnet/cap worn properly",
			"Staff grooming checked",
			"Hands washed before food handling",
			"Gloves used where required",
			"No visible illness/injury affecting food handling",
			"Jewellery/accessories removed where required",
			"Staff station allocation completed",
			"Daily staff briefing completed",
		]
	],
	*[
		_tick("Equipment Check", d)
		for d in [
			"Refrigerator",
			"Freezer",
			"Microwave",
			"Oven/Griller",
			"Fryer",
			"Mixer/Blender",
			"Juice Machine",
			"Tea/Coffee Equipment",
			"Induction/Gas Stove",
			"Water Purifier",
			"Dishwashing Equipment",
		]
	],
	_tick("POS & Payment System", "POS system switched on", **CRITICAL),
	*[
		_tick("POS & Payment System", d)
		for d in [
			"POS is connected to internet",
			"Printer is working",
			"Printer paper available",
			"Menu and prices are updated",
			"UPI/Payment QR is working",
			"MicroNxt(My Break) QR is working",
			"Petpooja/other billing system working",
			"Online aggregator apps are active",
		]
	],
	*[
		_tick("Packaging & Consumables", d)
		for d in [
			"Takeaway containers",
			"Cups",
			"Lids",
			"Carry bags",
			"Tissue/napkins",
			"Spoons/forks",
			"Straws",
			"Delivery packaging",
			"Product labels/stickers",
		]
	],
	*[
		_tick("Preparation & Production Readiness", d)
		for d in [
			"Daily preparation completed as per requirement",
			"Required sauces/chutneys/dips prepared",
			"Tea/coffee preparation items ready",
			"Juice/milkshake preparation items ready",
			"Cooking oil checked",
			"Required garnishes/toppings available",
			"All key ingredients available for today's menu",
			"Out-of-stock items identified and communicated",
			"Today's specials/promotions communicated to staff",
		]
	],
	*[
		_tick("Waste & Dishwashing", d)
		for d in [
			"Dishwashing area is clean and ready",
			"Clean water available",
			"Dishwashing chemicals available",
			"Garbage bins are clean and lined",
			"Food waste removed from previous day",
			"Waste segregation followed",
		]
	],
	*[
		_tick("Final Outlet Readiness", d)
		for d in [
			"All critical equipment is operational",
			"Required food stock is available",
			"Food safety standards are followed",
			"Staff are ready and properly groomed",
			"POS and payment systems are working",
			"Required packaging is available",
			"Production/preparation is complete",
			"Outlet is ready to accept customer orders",
		]
	],
]


# --------------------------- QSR-Closing Checklist ---------------------------

QSR_CLOSING_ITEMS = [
	*[
		_tick("Food & Raw Material Storage", d)
		for d in [
			"All leftover food has been checked before storage",
			"Food suitable for reuse is properly covered and stored",
			"All stored food is labelled with date/time",
			"Expired/spoiled food has been discarded",
			"Open food packets are properly sealed",
			"Raw and cooked food are stored separately",
			"All food items are stored at the required temperature",
			"Refrigerator temperature checked",
			"Freezer temperature checked",
			"FIFO/FEFO has been followed",
			"No food item has been left uncovered",
		]
	],
	_numeric("Food & Raw Material Storage", "Closing chiller temperature", standard="deg C"),
	_numeric("Food & Raw Material Storage", "Closing freezer temperature", standard="deg C"),
	*[
		_tick("Kitchen Cleaning", d)
		for d in [
			"All work tables cleaned and sanitised",
			"Cooking surfaces cleaned",
			"Stove/induction area cleaned",
			"Fryer area cleaned",
			"Griller/oven cleaned",
			"Mixer/blender cleaned",
			"Tea/coffee equipment cleaned",
			"Juice equipment cleaned",
			"Utensils washed and stored properly",
			"Cutting boards cleaned and sanitised",
			"Sinks cleaned",
			"Kitchen floor cleaned and dry",
			"No food particles or waste left on workstations",
		]
	],
	*[
		_tick("Dishwashing & Waste", d)
		for d in [
			"All dirty dishes have been washed",
			"Clean dishes stored properly",
			"Dishwashing area cleaned",
			"Dishwashing chemicals stored properly",
			"Food waste removed",
			"Waste bins emptied",
			"Bins cleaned and ready for next day",
			"Waste area left clean",
		]
	],
	*[
		_tick("Equipment Shutdown", d)
		for d in [
			"Gas stove switched off",
			"Gas cylinder/regulator checked and secured",
			"Induction switched off",
			"Fryer switched off",
			"Griller switched off",
			"Oven switched off",
			"Microwave switched off",
			"Mixer/blender switched off",
			"Juice machine switched off",
			"Tea/coffee equipment switched off as required",
			"Exhaust/hood switched off",
			"Non-essential electrical equipment switched off",
		]
	],
	*[
		_tick("Refrigerator & Freezer", d)
		for d in [
			"Refrigerator doors properly closed",
			"Freezer doors properly closed",
			"Food containers properly covered",
			"All stored food labelled",
			"No expired food inside",
			"No leakage/spillage inside refrigerator",
			"Temperature recorded",
			"Refrigerator/freezer alarms checked, if applicable",
		]
	],
	*[
		_tick("Stock & Inventory", d)
		for d in [
			"Fast-moving items checked",
			"Critical ingredients checked for next day",
			"Low-stock items identified",
			"Next-day purchase requirement prepared",
			"Wastage recorded",
			"Damaged/expired stock recorded",
			"Stock is properly stored and secured",
		]
	],
	_text("Stock & Inventory", "Wastage - product"),
	_numeric("Stock & Inventory", "Wastage - quantity"),
	_text("Stock & Inventory", "Wastage - reason"),
	*[
		_tick("POS & Sales Closing", d)
		for d in [
			"All pending orders completed",
			"No open bills remaining",
			"POS sales closed",
			"Cash counted",
			"Cash amount matches POS report",
			"Card/UPI/QR payments checked",
			"Online aggregator orders reconciled",
			"Petpooja/other POS closing completed",
			"Daily sales report submitted",
			"Cash deposited/secured as per company process",
		]
	],
	_numeric("POS & Sales Closing", "Closing sales - cash", standard="INR"),
	_numeric("POS & Sales Closing", "Closing sales - card", standard="INR"),
	_numeric("POS & Sales Closing", "Closing sales - UPI/QR", standard="INR"),
	_numeric("POS & Sales Closing", "Closing sales - aggregator", standard="INR"),
	_numeric("POS & Sales Closing", "Closing sales - total", standard="INR"),
	_numeric("POS & Sales Closing", "Cash variance", standard="INR"),
	*[
		_tick("Packaging & Consumables", d)
		for d in [
			"Takeaway containers stored properly",
			"Cups stored properly",
			"Lids stored properly",
			"Carry bags stored properly",
			"Tissues/napkins stored properly",
			"Spoons/forks/straws stored properly",
			"Delivery packaging stored properly",
			"No packaging material left exposed to contamination",
		]
	],
	_tick("Pest & Food Safety Check", "No visible insects/pests", **CRITICAL),
	*[
		_tick("Pest & Food Safety Check", d)
		for d in [
			"No food left exposed",
			"No food particles left overnight",
			"Drains checked and cleaned",
			"No stagnant water",
			"Doors/windows properly closed where applicable",
			"Pest-control issue reported if noticed",
		]
	],
	*[
		_tick("Security & Final Lock-Up", d)
		for d in [
			"Gas supply checked and secured",
			"Water taps checked",
			"Unnecessary electrical equipment switched off",
			"Refrigerator/freezer left ON",
			"Kitchen equipment secured",
			"Store/stock area secured",
			"Cash secured as per company procedure",
			"POS/payment devices secured",
			"Outlet doors/shutters properly locked",
			"Final outlet inspection completed",
		]
	],
]


# --------------------------- QSR-Weekly Checklist ---------------------------

QSR_WEEKLY_ITEMS = [
	*[
		_tick("Licences, Certificates & Compliance", d)
		for d in [
			"FSSAI licence is displayed at the outlet",
		]
	],
	_tick(
		"Licences, Certificates & Compliance", "FSSAI licence is valid and not expired", **CRITICAL
	),
	*[
		_tick("Licences, Certificates & Compliance", d)
		for d in [
			"FSSAI licence details match the outlet",
			"Required local trade/business licence is displayed",
			"Local licence/certificate is valid",
			"Fire safety certificate/NOC is available where applicable",
		]
	],
	_tick("Licences, Certificates & Compliance", "Fire safety certificate is valid", **CRITICAL),
	*[
		_tick("Licences, Certificates & Compliance", d)
		for d in [
			"Pest-control records/certificates are available",
			"Required food safety/display notices are displayed",
			"All displayed licences/certificates are clearly visible to customers/officials",
		]
	],
	_text("Licences, Certificates & Compliance", "Licence name"),
	_text("Licences, Certificates & Compliance", "Licence number"),
	_text("Licences, Certificates & Compliance", "Expiry / valid until"),
	*[
		_tick("Kitchen Deep Cleaning", d)
		for d in [
			"Exhaust hood cleaned",
			"Exhaust filters cleaned",
			"Walls behind cooking equipment cleaned",
			"Under-counter areas cleaned",
			"Refrigerator interior cleaned",
			"Freezer interior cleaned",
			"Refrigerator coils/ventilation checked",
			"Oven/griller deep cleaned",
			"Fryer deep cleaned",
			"Mixer/blender deep cleaned",
			"Juice/coffee/tea equipment deep cleaned",
			"Storage shelves cleaned",
			"Drains cleaned",
			"Hard-to-reach areas cleaned",
		]
	],
	_tick("Pest Control", "No cockroach/insect activity observed", **CRITICAL),
	_tick("Pest Control", "No rodent activity observed", **CRITICAL),
	*[
		_tick("Pest Control", d)
		for d in [
			"No flies/pests observed around food",
			"Pest-control points checked",
			"Pest-control treatment completed as scheduled",
			"Pest-control records available",
			"No gaps/openings that could allow pest entry",
			"No stagnant water or pest breeding areas",
		]
	],
	*[
		_tick("Stock & Inventory", d)
		for d in [
			"Physical stock matches system/records",
			"Major stock variances checked",
			"Slow-moving items identified",
			"Expiring products identified",
			"Wastage records maintained",
			"Damaged products recorded",
			"Packaging stock checked",
			"Critical items have sufficient stock",
			"Purchase requirements prepared",
		]
	],
	_tick("Safety & Emergency Equipment", "Fire extinguishers available", **CRITICAL),
	*[
		_tick("Safety & Emergency Equipment", d)
		for d in [
			"Fire extinguishers are accessible",
			"Fire extinguisher inspection/service date checked",
			"Gas pipe/regulator condition checked",
			"Electrical wires/sockets checked",
			"No exposed/damaged electrical wiring",
			"Emergency contact numbers displayed",
			"First-aid kit available",
			"First-aid kit adequately stocked",
			"Emergency exits/access routes are clear",
		]
	],
	*[
		_tick("Documents & Records", d)
		for d in [
			"Daily opening checklists completed",
			"Daily closing checklists completed",
			"Temperature records maintained",
			"Cleaning records maintained",
			"Pest-control records maintained",
			"Wastage records maintained",
			"Purchase invoices properly maintained",
			"Stock records updated",
			"Equipment maintenance records updated",
			"Customer complaints recorded and closed",
		]
	],
]


# --------------------------- FC-Manager Opening Checklist ---------------------------

FC_OPENING_ITEMS = [
	*[
		_tick("Overall Food Court Readiness", d)
		for d in [
			"Food court is ready before opening time",
			"All scheduled outlets are open on time",
			"No outlet has an opening delay",
			"Common area housekeeping completed",
			"Dining tables and chairs are clean and arranged",
			"Floors are clean and dry",
			"Dustbins are clean and properly positioned",
			"No bad smell noticed",
			"Lighting is working",
			"AC/fans are working",
			"Music/display systems working where applicable",
		]
	],
	_tick("Outlet Opening Status", "All outlet managers completed their opening checklist"),
	_tick(
		"Outlet Opening Status", "Critical issues reported by outlets reviewed", **CRITICAL
	),
	_tick(
		"Outlet Opening Status",
		"No outlet has an unresolved critical food-safety issue",
		**CRITICAL,
	),
	*[
		_tick("Food Safety & Hygiene", d)
		for d in [
			"General food handling practices observed",
			"Staff are wearing proper uniforms/hairnets",
			"No exposed food observed",
			"Food storage practices appear satisfactory",
			"Handwashing facilities available",
			"No visible pest activity",
			"Waste is being managed properly",
			"No dirty utensils/plates accumulating in working areas",
		]
	],
	*[
		_tick("Staff & Attendance", d)
		for d in [
			"All outlet managers present",
			"Staff shortage identified",
			"Staff deployed according to requirement",
			"Staff grooming checked",
			"Any absenteeism reported to management",
			"Security/housekeeping staff present as required",
		]
	],
	*[
		_tick("Equipment & Maintenance", d)
		for d in [
			"Common equipment/services operational",
			"Water supply available",
			"Electrical supply normal",
			"Common exhaust/ventilation working where applicable",
			"No leakage noticed",
			"No major maintenance issue pending",
			"Previous day's maintenance issues followed up",
		]
	],
	*[
		_tick("Licences & Compliance", d)
		for d in [
			"Required licences/certificates are displayed",
			"FSSAI licence displayed at applicable outlet",
		]
	],
	_tick("Licences & Compliance", "Licences are within validity period", **CRITICAL),
	*[
		_tick("Licences & Compliance", d)
		for d in [
			"No expired certificate identified",
			"Required food safety information is displayed",
			"Any compliance issue escalated",
		]
	],
]


# --------------------------- FC-Manager Mid-Day Checklist ---------------------------

FC_MIDDAY_ITEMS = [
	*[
		_tick("Outlet Operations", d)
		for d in [
			"All outlets are operating",
			"No outlet has stopped service without approval",
			"Staff shortages managed",
			"Customer queues are under control",
			"POS/payment systems functioning",
			"Online orders functioning where applicable",
		]
	],
	*[
		_tick("Food Quality & Hygiene", d)
		for d in [
			"Food is being handled hygienically",
			"No uncovered food observed",
			"Staff hygiene maintained",
			"Work areas reasonably clean",
			"No excessive food wastage observed",
			"No pest activity observed",
			"Dirty plates/utensils are not accumulating",
			"Waste is being cleared regularly",
		]
	],
	*[
		_tick("Customer Experience", d)
		for d in [
			"Dining area clean",
			"Tables cleared regularly",
			"Customer complaints checked",
			"Complaints are being resolved promptly",
			"No major service delays",
			"Food court ambience acceptable",
		]
	],
	*[
		_tick("Sales & Business", d)
		for d in [
			"Outlet sales reviewed",
			"Any major sales drop identified",
			"Promotions being displayed correctly",
			"QR/payment promotions functioning",
			"Online aggregator orders checked",
			"Out-of-stock items reviewed",
		]
	],
	*[
		_tick("Maintenance", d)
		for d in [
			"No water leakage",
			"No electrical issue",
			"No equipment breakdown affecting business",
			"AC/ventilation functioning",
			"Any maintenance complaint followed up",
		]
	],
]


# --------------------------- FC-Manager Closing Checklist ---------------------------

FC_CLOSING_ITEMS = [
	_tick("Outlet Closing Status", "All outlet closing checklists completed"),
	_tick(
		"Outlet Closing Status", "No outlet has left critical issues unresolved", **CRITICAL
	),
	*[
		_tick("Outlet Closing Status", d)
		for d in [
			"Food has been properly stored",
			"Food wastage has been recorded",
			"Refrigerators/freezers are operating",
			"Gas/equipment shutdown confirmed as applicable",
		]
	],
	*[
		_tick("Common Area Closing", d)
		for d in [
			"Dining area cleaned",
			"Tables/chairs cleaned and arranged",
			"Floors cleaned",
			"Dustbins emptied",
			"Waste removed from food court",
			"Dish/dirty plate movement stopped",
			"No food waste left in common areas",
			"No bad smell noticed",
		]
	],
	_tick("Food Safety", "No exposed food left overnight", **CRITICAL),
	*[
		_tick("Food Safety", d)
		for d in [
			"No food waste left in outlet/common area",
			"No pest activity observed",
			"Food court kitchen/service areas checked",
			"Water/drainage issues checked",
			"Food safety complaints/issues recorded",
		]
	],
	*[
		_tick("Cash & POS", d)
		for d in [
			"All outlets completed daily sales closing",
			"Major cash/POS variances checked",
			"Payment/QR issues reviewed",
			"Online order reconciliation completed where applicable",
			"Any unexplained variance reported",
		]
	],
	*[
		_tick("Security & Safety", d)
		for d in [
			"All outlets locked as per procedure",
			"Common electrical equipment checked",
			"Unnecessary lights/equipment switched off",
			"Water taps checked",
			"Gas safety confirmed at applicable outlets",
			"Fire exits/access routes clear",
			"Security informed of any special issue",
			"Food court final inspection completed",
		]
	],
]


# --------------------------- FC-Manager Weekly Checklist ---------------------------

FC_WEEKLY_ITEMS = [
	*[
		_tick("Outlet Compliance", d)
		for d in [
			"Opening checklists being completed",
			"Closing checklists being completed",
			"Daily operational checks being completed",
			"Outlet SOPs being followed",
			"Staff attendance maintained",
			"Staff grooming standards maintained",
		]
	],
	_tick("Outlet Compliance", "Food safety standards maintained", **CRITICAL),
	*[
		_tick("Outlet Compliance", d)
		for d in [
			"No repeated complaints from the outlet",
			"Repeated issues escalated",
		]
	],
	*[
		_tick("Food Safety Audit", d)
		for d in [
			"Food storage checked",
			"FIFO/FEFO being followed",
			"Expiry dates checked",
			"Food labelling checked",
			"Temperature records reviewed",
			"Raw/cooked food separation checked",
			"Cleaning records reviewed",
			"Pest-control records checked",
		]
	],
	_tick("Food Safety Audit", "No major food safety violation identified", **CRITICAL),
	_tick("Food Safety Audit", "Corrective actions from previous week closed"),
	*[
		_tick("Licences & Certificates", d)
		for d in [
			"FSSAI licences displayed",
		]
	],
	_tick("Licences & Certificates", "FSSAI licences valid", **CRITICAL),
	*[
		_tick("Licences & Certificates", d)
		for d in [
			"Trade/business licences displayed where required",
			"Trade/business licences valid",
			"Fire safety documents available where applicable",
			"Fire safety documents valid",
			"Pest-control records available",
			"Other required certificates displayed",
		]
	],
	_tick("Licences & Certificates", "No licence/certificate is expired", **CRITICAL),
	_tick("Licences & Certificates", "Renewal requirements identified in advance"),
	*[
		_tick("Common Area & Customer Experience", d)
		for d in [
			"Dining area condition checked",
			"Tables/chairs condition checked",
			"Flooring condition checked",
			"Common dustbins checked",
			"Wash area/washroom condition checked if under food court responsibility",
			"Lighting checked",
			"AC/ventilation checked",
			"Customer complaints reviewed",
			"Customer feedback reviewed",
			"Recurring customer complaints identified",
		]
	],
	*[
		_tick("Maintenance", d)
		for d in [
			"Pending maintenance list reviewed",
			"Equipment breakdowns reviewed",
			"Electrical issues reviewed",
			"Plumbing issues reviewed",
			"Leakage issues reviewed",
			"Pest-control issues reviewed",
			"Civil/repair requirements identified",
			"Previous week's maintenance issues closed",
		]
	],
	*[
		_tick("Sales & Business Review", d)
		for d in [
			"Weekly sales reviewed outlet-wise",
			"Low-performing outlets identified",
			"Out-of-stock issues reviewed",
			"Food wastage reviewed",
			"Customer complaints reviewed",
			"Promotions reviewed",
			"QR/payment performance reviewed",
			"Aggregator performance reviewed where applicable",
		]
	],
	*[
		_tick("Staff & Training", d)
		for d in [
			"Staff shortage reviewed",
			"Attendance issues reviewed",
			"Grooming compliance checked",
			"Food safety training requirements identified",
			"New staff properly trained",
			"Staff complaints/issues reviewed",
			"SOP training conducted where required",
		]
	],
]


TEMPLATES = [
	{
		"template_name": "QSR Opening Checklist",
		"shift_type": "Pre-Opening",
		"checklist_scope": "Outlet",
		"frequency": "Daily",
		"items": QSR_OPENING_ITEMS,
	},
	{
		"template_name": "QSR Closing Checklist",
		"shift_type": "Closing",
		"checklist_scope": "Outlet",
		"frequency": "Daily",
		"items": QSR_CLOSING_ITEMS,
	},
	{
		"template_name": "QSR Weekly Inspection Checklist",
		"shift_type": "Weekly Audit",
		"checklist_scope": "Outlet",
		"frequency": "Weekly",
		"weekly_day": "Monday",
		"items": QSR_WEEKLY_ITEMS,
	},
	{
		"template_name": "FC-Manager Daily Opening Checklist",
		"shift_type": "Pre-Opening",
		"checklist_scope": "Food Court",
		"frequency": "Daily",
		"items": FC_OPENING_ITEMS,
	},
	{
		"template_name": "FC-Manager Daily Mid-Day Checklist",
		"shift_type": "Mid-Day",
		"checklist_scope": "Food Court",
		"frequency": "Daily",
		"items": FC_MIDDAY_ITEMS,
	},
	{
		"template_name": "FC-Manager Daily Closing Checklist",
		"shift_type": "Closing",
		"checklist_scope": "Food Court",
		"frequency": "Daily",
		"items": FC_CLOSING_ITEMS,
	},
	{
		"template_name": "FC-Manager Weekly Audit Checklist",
		"shift_type": "Weekly Audit",
		"checklist_scope": "Food Court",
		"frequency": "Weekly",
		"weekly_day": "Monday",
		"items": FC_WEEKLY_ITEMS,
	},
]

# Outlets excluded from the per-outlet QSR fan-out - "Common Area" is the
# placeholder outlet seed_demo_checklist_template.py creates purely so the
# old demo template had somewhere to point; it isn't a real outlet.
EXCLUDED_OUTLETS = {"Common Area"}


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
	frappe.reload_doc("retail_sop", "doctype", "checklist_category")
	frappe.reload_doc("retail_sop", "doctype", "checklist_template_item")
	frappe.reload_doc("retail_sop", "doctype", "checklist_template")
	frappe.reload_doc("retail_sop", "doctype", "outlet")

	# The placeholder demo template is superseded by the real content
	# below - deactivate (not delete) it so it stops being auto-created
	# daily, while any historical Shift Checklist that already references
	# it stays intact.
	if frappe.db.exists("Checklist Template", "Pre-Opening Demo"):
		frappe.db.set_value("Checklist Template", "Pre-Opening Demo", "active", 0)

	for spec in TEMPLATES:
		_ensure_categories(spec["items"])

		if spec["checklist_scope"] == "Food Court":
			_create_template(spec["template_name"], None, spec)
			continue

		outlets = frappe.get_all(
			"Outlet",
			filters={"active": 1, "name": ["not in", EXCLUDED_OUTLETS]},
			pluck="name",
		)
		for outlet in outlets:
			_create_template(f"{spec['template_name']} - {outlet}", outlet, spec)
