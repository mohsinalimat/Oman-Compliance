import frappe

from oman_compliance.oman_compliance.utils.migration import migrate_oman_vat_settings


def execute() -> None:
	result = migrate_oman_vat_settings()

	if result["needs_review"]:
		# frappe.msgprint() targets a web request's client-side message log — invisible here, since
		# this runs from `bench migrate`'s terminal context, not a web request. print() is what
		# actually reaches the admin running the migration.
		print(
			f"Oman VAT Migration: migrated {result['accounts_migrated']} VAT Account row(s) and"
			f" {result['trns_migrated']} Company TRN(s) from the legacy oman_vat app."
			f" {len(result['needs_review'])} record(s) could not be migrated automatically and need"
			" manual review — see the Error Log for details."
		)
		frappe.log_error(
			title="Oman VAT Migration: records needing manual review",
			message=frappe.as_json(result["needs_review"]),
		)
