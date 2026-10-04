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

import json

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

# Workspace-only text (not part of the frontend's get_domain_info()
# contract - relabel_workspace() below is the only consumer).
_WORKSPACE_TEXT = {
	"store": {
		"title": "Retail SOP",
		"tagline": "Multi-outlet food court SOP &amp; compliance checklists.",
	},
	"office": {
		"title": "Office SOP",
		"tagline": "Multi-location office SOP &amp; compliance checklists.",
	},
	"facility": {
		"title": "Facility SOP",
		"tagline": "Multi-facility SOP &amp; compliance checklists.",
	},
}


def get_domain():
	domain = frappe.conf.get(CONF_KEY)
	return domain if domain in LABELS else DEFAULT_DOMAIN


def get_labels():
	return LABELS[get_domain()]


def relabel_workspace():
	"""Keeps the "Retail SOP" Desk workspace's Outlet shortcut/link label
	and header text in sync with the configured domain - about the only
	Desk-facing text Frappe lets us override without renaming anything
	(see README §14 - Role names and the Outlet doctype's own
	breadcrumb/list title are tied to their real record name and are
	deliberately left alone). Deliberately does NOT touch the Workspace
	document's own `title`/`label` fields - those double as its naming
	field, and changing them risks an implicit rename of the record
	itself (from "Retail SOP" to something this function's own `exists`
	check below would then stop finding).

	Registered as an `after_migrate` hook (hooks.py) rather than a
	one-off patch, for two reasons: it needs to re-run (and relabel
	again) if `retail_sop_domain` is ever changed on an already-migrated
	site, and `bench migrate` re-syncs this workspace from its own
	checked-in fixture (retail_sop/workspace/retail_sop/retail_sop.json,
	committed under the "store" wording) on every run - a one-time patch
	could get silently overwritten back to "Outlet" by that sync.
	Matches outlet shortcuts/links by `link_to == "Outlet"` (the actual
	doctype, never relabelled) rather than by their current label text,
	and matches header/paragraph content blocks by their stable `id`
	rather than their current text, so this is correct regardless of
	which domain last ran it.

	**Not verified against a live bench** (same caveat already on this
	workspace's content-block schema in README §10/11): the assumption
	that a `content` block's `shortcut_name`/`card_name` is matched
	against the corresponding `shortcuts`/`links` row's `label` (not a
	separate stable key) is from Frappe's documented Workspace schema,
	not confirmed by actually loading this page.
	"""
	if not frappe.db.exists("Workspace", "Retail SOP"):
		return

	labels = get_labels()
	text = _WORKSPACE_TEXT[get_domain()]
	all_outlet_labels = {domain_labels["outlet"] for domain_labels in LABELS.values()}

	doc = frappe.get_doc("Workspace", "Retail SOP")
	changed = False

	for row in list(doc.shortcuts) + list(doc.links):
		if row.link_to == "Outlet" and row.label != labels["outlet"]:
			row.label = labels["outlet"]
			changed = True

	if doc.content:
		content = json.loads(doc.content)
		for block in content:
			data = block.get("data", {})
			if block.get("id") == "rsop_header":
				new_text = f'<span class="h4"><b>{text["title"]}</b></span>'
			elif block.get("id") == "rsop_para":
				new_text = f'<span class="text-muted">{text["tagline"]}</span>'
			elif block.get("type") == "shortcut" and data.get("shortcut_name") in all_outlet_labels:
				if data["shortcut_name"] != labels["outlet"]:
					data["shortcut_name"] = labels["outlet"]
					changed = True
				continue
			else:
				continue
			if data.get("text") != new_text:
				data["text"] = new_text
				changed = True
		if changed:
			doc.content = json.dumps(content)

	if changed:
		doc.save(ignore_permissions=True)
