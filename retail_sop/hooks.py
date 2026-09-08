app_name = "retail_sop"
app_title = "Retail SOP"
app_publisher = "Micronxt"
app_description = "Multi-outlet food court SOP & compliance checklist system"
app_email = "vijay@micronxt.com"
app_license = "mit"

# This app is installed on top of an existing ERPNext bench and links to
# core doctypes (Employee, Customer). If Employee lives in a separate
# "hrms" app on the target bench, add "hrms" here too.
required_apps = ["frappe", "erpnext"]

# Includes in <head>
# ------------------
doctype_js = {
	"Shift Checklist": "public/js/shift_checklist.js",
}

# Fixtures
# --------
# Ships the two custom roles and the Draft -> Submitted -> Verified
# workflow config for Shift Checklist declaratively, so they exist right
# after `bench install-app` / `bench migrate` without a manual setup step.
fixtures = [
	{
		"dt": "Role",
		"filters": [["role_name", "in", ["Food Court Supervisor", "Food Court Manager"]]],
	},
	{
		"dt": "Workflow State",
		"filters": [["name", "in", ["Draft", "Submitted", "Verified"]]],
	},
	{
		"dt": "Workflow Action Master",
		"filters": [["name", "in", ["Submit", "Verify"]]],
	},
	{
		"dt": "Workflow",
		"filters": [["name", "=", "Shift Checklist Workflow"]],
	},
	{
		"dt": "Notification",
		"filters": [["name", "=", "Critical Checklist Deviation Alert"]],
	},
]

# Scheduled tasks
# ---------------
scheduler_events = {
	"daily": [
		"retail_sop.tasks.create_daily_shift_checklists",
	],
}

# JWT bearer-token auth bypass
# ----------------------------
# Runs on every request. If a valid `Authorization: Bearer <access_token>`
# header is present, this makes the request run as that real Frappe user
# with no `sid` cookie/CSRF involved at all - see retail_sop/auth/ for the
# whole flow (login/refresh/logout endpoints, JWT signing, this hook).
# Requires `retail_sop_jwt_keys` / `retail_sop_jwt_active_kid` to be set in
# site_config.json (see retail_sop/auth/jwt_utils.py) before login() will
# work; the hook itself fails safe (falls through to Guest) if they're not.
before_request = [
	"retail_sop.auth.middleware.authenticate_request",
]
