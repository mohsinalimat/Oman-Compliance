import frappe


def execute() -> None:
	# generated_for_company/from_date/to_date let validate() detect a return whose boxes no
	# longer match its own header (see oman_vat_return.py's _clear_boxes_if_stale()). Any return
	# saved under the old schema has these fields empty, which would otherwise read as "stale" on
	# its next save and have its boxes wiped for no actual reason — backfill them from the
	# return's own current header instead. This assumes each return's existing header is already
	# correct for its existing boxes; it can't recover or flag a return whose header was already
	# edited out of sync with its boxes before this fix existed, since no record of the values
	# actually used at generation time exists prior to this patch. Harmless to run for a return
	# with no boxes yet too, since _boxes_are_stale() only looks at these fields once boxes is
	# non-empty.
	frappe.db.sql(
		"""
		update `tabOman VAT Return`
		set generated_for_company = company,
			generated_for_from_date = from_date,
			generated_for_to_date = to_date
		where generated_for_company is null
		"""
	)
