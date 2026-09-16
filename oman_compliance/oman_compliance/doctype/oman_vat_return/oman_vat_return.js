frappe.ui.form.on("Oman VAT Return", {
	generate_return(frm) {
		frm.call("generate_return").then(() => frm.reload_doc());
	},
});
