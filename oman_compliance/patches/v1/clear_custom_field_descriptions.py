import frappe

from oman_compliance.oman_compliance.constants.custom_fields import CUSTOM_FIELDS


def execute() -> None:
	# create_custom_fields()'s update() only sets keys present in CUSTOM_FIELDS - it never
	# clears a DB column dropped from the source dict, so removing "description" there left
	# existing Custom Field records with their old text. Blank it out explicitly here.
	for doctypes, fields in CUSTOM_FIELDS.items():
		if isinstance(doctypes, str):
			doctypes = (doctypes,)
		if isinstance(fields, dict):
			fields = (fields,)

		for doctype in doctypes:
			for df in fields:
				frappe.db.set_value(
					"Custom Field",
					{"dt": doctype, "fieldname": df["fieldname"]},
					"description",
					"",
				)
