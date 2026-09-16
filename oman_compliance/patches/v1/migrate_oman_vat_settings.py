import frappe
from frappe import _

from oman_compliance.oman_compliance.utils.migration import migrate_oman_vat_settings


def execute() -> None:
	result = migrate_oman_vat_settings()

	if result["needs_review"]:
		frappe.msgprint(
			_(
				"Migrated {0} VAT Account row(s) and {1} Company TRN(s) from the legacy oman_vat app."
				" {2} record(s) could not be migrated automatically and need manual review — see the"
				" Error Log for details."
			).format(result["accounts_migrated"], result["trns_migrated"], len(result["needs_review"])),
			title=_("Oman VAT Migration"),
			indicator="orange",
		)
		frappe.log_error(
			title="Oman VAT Migration: records needing manual review",
			message=frappe.as_json(result["needs_review"]),
		)
