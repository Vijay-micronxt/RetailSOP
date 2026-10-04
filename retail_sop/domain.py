"""Which business vertical this site is running: the original food-court/
retail SOP app, or a generic office/facility-management install using the
same doctypes (Outlet, Checklist Template, Shift Checklist, ...) under
different terminology.

Nothing structural changes per domain - no doctype or role is renamed, no
permission check is domain-aware. "Domain" only controls two things:
  1. The display labels returned by get_labels() (consumed by the
     frontend via api.get_domain_info, and by nothing on the Desk side -
     Desk keeps showing the real doctype/role names regardless).
  2. Which patches/v0_0/seed_*_sop.py content patch installs its demo
     checklist templates (see each patch's own domain gate).

Set in site_config.json:

    "retail_sop_domain": "office"

Unset, or set to anything not in DOMAINS, falls back to "store" - the
original implementation - so every existing site keeps behaving exactly
as it already does.
"""

import frappe

CONF_KEY = "retail_sop_domain"
DEFAULT_DOMAIN = "store"

LABELS = {
	"store": {
		"outlet": "Outlet",
		"outlet_plural": "Outlets",
		"operator_role": "Store Operator",
		"supervisor_role": "Food Court Supervisor",
		"manager_role": "Food Court Manager",
		"scope_unit": "Outlet",
		"scope_wide": "Food Court",
	},
	"office": {
		"outlet": "Office",
		"outlet_plural": "Offices",
		"operator_role": "Office Operator",
		"supervisor_role": "Office Supervisor",
		"manager_role": "Office Manager",
		"scope_unit": "Office",
		"scope_wide": "Organization",
	},
	"facility": {
		"outlet": "Facility",
		"outlet_plural": "Facilities",
		"operator_role": "Facility Operator",
		"supervisor_role": "Facility Supervisor",
		"manager_role": "Facility Manager",
		"scope_unit": "Facility",
		"scope_wide": "Organization",
	},
}

DOMAINS = list(LABELS)


def get_domain():
	domain = frappe.conf.get(CONF_KEY)
	return domain if domain in LABELS else DEFAULT_DOMAIN


def get_labels():
	return LABELS[get_domain()]
