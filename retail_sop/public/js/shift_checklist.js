// Desk UI fallback only. The real data-entry path is the Lovable frontend
// calling `update_check_item` in retail_sop/api.py, which does its own
// server-side stamping of checked_at/checked_by independently of this
// script. This only matters if someone edits a Shift Checklist directly
// through the Frappe desk form.
frappe.ui.form.on("Shift Checklist Item", {
	status: function (frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (!row.status) {
			return;
		}
		frappe.model.set_value(cdt, cdn, "checked_at", frappe.datetime.now_datetime());
		frappe.model.set_value(cdt, cdn, "checked_by", frappe.session.user);
		frm.refresh_field("items");
	},
});
