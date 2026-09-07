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

// sr_no/check_description/category/standard on Shift Checklist Item are
// read-only fetch_from fields (fetched from the hidden `template_item`
// link). The scheduler sets that link when it auto-creates a checklist;
// a checklist created manually in Desk has no rows and no way to get any,
// so pull them in from the selected Checklist Template here instead.
frappe.ui.form.on("Shift Checklist", {
	checklist_template: function (frm) {
		if (frm.doc.checklist_template) {
			retail_sop_populate_items_from_template(frm);
		}
	},
	refresh: function (frm) {
		if (frm.doc.checklist_template && frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Get Items From Template"), function () {
				retail_sop_populate_items_from_template(frm);
			});
		}
	},
});

function retail_sop_populate_items_from_template(frm) {
	frappe.call({
		method: "retail_sop.retail_sop.doctype.shift_checklist.shift_checklist.get_template_items",
		args: { checklist_template: frm.doc.checklist_template },
		callback: function (r) {
			if (!r.message || !r.message.length) {
				frappe.msgprint(__("Selected template has no items."));
				return;
			}
			frm.clear_table("items");
			r.message.forEach(function (template_item) {
				let row = frm.add_child("items");
				row.template_item = template_item.name;
				row.sr_no = template_item.sr_no;
				row.check_description = template_item.check_description;
				row.category = template_item.category;
				row.standard = template_item.standard;
			});
			frm.refresh_field("items");
			frm.dirty();
		},
	});
}
