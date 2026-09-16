import frappe


def execute() -> None:
	# CustomField.validate() only recomputes idx from insert_after for a brand-new field, not an
	# existing one being updated (see custom_field.py) - so grouping these under a new Section/
	# Column Break requires deleting them first so the create_custom_fields() call right after
	# this patch recreates them fresh, in the new order.
	frappe.db.delete(
		"Custom Field",
		{
			"dt": "Purchase Invoice",
			"fieldname": (
				"in",
				["is_reverse_charge", "is_gcc_supplier", "is_import_of_goods", "is_postponed_import_vat"],
			),
		},
	)
