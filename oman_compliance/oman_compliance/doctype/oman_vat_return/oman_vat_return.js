frappe.ui.form.on("Oman VAT Return", {
	refresh(frm) {
		if (frm.doc.status === "Draft" && !frm.is_new()) {
			frm.add_custom_button(__("Generate Return"), () => {
				frm.call("generate_return").then(() => frm.reload_doc());
			});

			if (frm.doc.boxes && frm.doc.boxes.length) {
				frm.add_custom_button(__("Mark as Filed"), () => {
					frappe.confirm(
						__(
							"Filing this return locks it permanently — it can no longer be edited, regenerated, or deleted. Continue?"
						),
						() => frm.call("mark_as_filed").then(() => frm.reload_doc())
					);
				});
			}
		}
	},
});
