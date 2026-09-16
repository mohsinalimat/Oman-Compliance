frappe.ui.form.on("Oman VAT Return", {
	refresh(frm) {
		if (frm.doc.status === "Draft" && !frm.is_new()) {
			frm.add_custom_button(__("Generate Return"), () => {
				frm.call("generate_return").then(() => frm.reload_doc());
			});
		}
	},
});
