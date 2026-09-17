import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_first_day, get_last_day, getdate

from oman_compliance.oman_compliance.utils.vat_return.sections.domestic_supplies import get_domestic_supplies
from oman_compliance.oman_compliance.utils.vat_return.sections.exports import get_exports
from oman_compliance.oman_compliance.utils.vat_return.sections.imports_of_goods import get_imports_of_goods
from oman_compliance.oman_compliance.utils.vat_return.sections.input_vat_credit import get_input_vat_credit
from oman_compliance.oman_compliance.utils.vat_return.sections.reverse_charge_purchases import (
	get_reverse_charge_purchases,
)
from oman_compliance.oman_compliance.utils.vat_return.totals import (
	get_input_vat_credit_total,
	get_net_tax_liability,
	get_total_vat_due,
)

_EMPTY_BOX = {
	"taxable_amount": 0.0,
	"vat_amount": 0.0,
	"adjustment_taxable_amount": 0.0,
	"adjustment_vat_amount": 0.0,
}

_QUARTER_START_MONTHS = (1, 4, 7, 10)


class OmanVATReturn(Document):
	def validate(self):
		if self.from_date and self.to_date and self.from_date > self.to_date:
			frappe.throw(_("From Date cannot be after To Date"))

		if self.from_date and self.to_date:
			self.period_type = self._determine_period_type()

		self.validate_filed_is_immutable()
		self._clear_boxes_if_stale()

	def _determine_period_type(self) -> str:
		"""Oman VAT returns are always filed for a whole calendar period — never a partial month
		or an off-quarter span — so `period_type` isn't user input, it's derived from From/To Date
		and the field is read-only. A range that isn't exactly one calendar month or one standard
		calendar quarter (Jan-Mar/Apr-Jun/Jul-Sep/Oct-Dec) is rejected outright rather than guessed
		at."""
		from_date = getdate(self.from_date)
		to_date = getdate(self.to_date)

		if from_date == get_first_day(from_date) and to_date == get_last_day(from_date):
			return "Monthly"

		if from_date.month in _QUARTER_START_MONTHS and from_date == get_first_day(from_date):
			quarter_end = get_last_day(get_first_day(from_date, d_months=2))
			if to_date == quarter_end:
				return "Quarterly"

		frappe.throw(
			_(
				"From Date and To Date must span exactly one calendar month, or one standard "
				"calendar quarter (Jan-Mar, Apr-Jun, Jul-Sep, Oct-Dec)."
			),
			title=_("Invalid Period"),
		)

	def validate_filed_is_immutable(self):
		"""A Filed return must not change under a user's feet — not just via generate_return()
		(which already refuses to regenerate), but via any edit at all, including a plain field
		change or reverting `status` itself back to Draft. Once the DB's own copy of this document
		says Filed, every subsequent save is rejected outright; the one save that's still allowed is
		the Draft → Filed transition itself, since that's what "filing" actually is."""
		if self.is_new():
			return

		if self._get_locked_persisted_status() == "Filed":
			frappe.throw(_("A Filed return cannot be modified."), title=_("Return Already Filed"))

	def _boxes_are_stale(self) -> bool:
		"""`boxes` is a point-in-time snapshot computed by generate_return() from company/from_date/
		to_date — those three fields stay editable afterwards, so both a plain save() and
		mark_as_filed() need to detect a now-mismatched snapshot rather than trusting `boxes` being
		non-empty on its own. This deliberately doesn't use Document.has_value_changed(), even
		though that's the idiomatic Frappe way to compare against the last-persisted value: it
		would compare against the header *before this save*, not against what `boxes` was actually
		generated for — so changing From Date and clicking Generate Return again in the same save
		would see "from_date changed" and immediately wipe the very boxes generate_return() just
		computed for the new date. Stamping generated_for_* only inside generate_return() itself
		avoids that false positive."""
		if not self.boxes:
			return False

		if not (self.generated_for_company and self.generated_for_from_date and self.generated_for_to_date):
			return True

		return not (
			self.company == self.generated_for_company
			and getdate(self.from_date) == getdate(self.generated_for_from_date)
			and getdate(self.to_date) == getdate(self.generated_for_to_date)
		)

	def _clear_boxes_if_stale(self):
		"""Reset to an ungenerated state once boxes no longer match the header: mark_as_filed()
		already refuses to file empty boxes, and the "Mark as Filed" button is gated on boxes being
		non-empty, so this alone forces a regenerate before the return can be filed again."""
		if not self._boxes_are_stale():
			return

		self.boxes = []
		self.total_vat_due = 0
		self.input_vat_credit_total = 0
		self.net_tax_liability = 0
		self.generated_for_company = None
		self.generated_for_from_date = None
		self.generated_for_to_date = None

		frappe.msgprint(
			_(
				"Company/From Date/To Date changed since the return was generated — boxes were cleared. Regenerate the return."
			),
			indicator="orange",
			alert=True,
		)

	def on_trash(self):
		# Reads the persisted status fresh rather than trusting self.status: a doc instance loaded
		# before another request filed this same return would otherwise still say "Draft" in
		# memory and sail through this check, deleting a return that's actually Filed in the
		# database. Same reasoning as validate_filed_is_immutable() above.
		if self._get_locked_persisted_status() == "Filed":
			frappe.throw(_("A Filed return cannot be deleted."), title=_("Return Already Filed"))

	def _get_locked_persisted_status(self) -> str | None:
		"""A plain `frappe.db.get_value()` read (the default `for_update=False`) would still leave
		a race: one request could read "Draft" a moment before a second, concurrent request files
		the return and commits, and the first request's save/delete — already past its own check —
		would still go through once its transaction commits. `for_update=True` instead takes a row
		lock on this document for the rest of the *current* transaction, so a second concurrent
		save/delete blocks here until the first one commits, then reads the up-to-date status rather
		than racing past a stale one — validate()/on_trash() both run inside the same transaction as
		the mutation they're guarding, so the lock actually covers the write, not just the read."""
		return frappe.db.get_value(self.doctype, self.name, "status", for_update=True)

	@frappe.whitelist()
	def generate_return(self):
		"""Recomputes every box from the current transaction data and replaces `boxes` wholesale —
		safe to call repeatedly while still Draft, since it's meant to be re-run as invoices for the
		period get corrected. Locked once Filed, matching how a filed government return shouldn't
		silently change under a user's feet."""
		if self.status == "Filed":
			frappe.throw(_("Cannot regenerate a Filed return."))

		if not (self.company and self.from_date and self.to_date):
			frappe.throw(_("Company, From Date and To Date are required before generating a return."))

		domestic_supplies = get_domestic_supplies(self.company, self.from_date, self.to_date)
		exports = get_exports(self.company, self.from_date, self.to_date)
		reverse_charge_purchases = get_reverse_charge_purchases(self.company, self.from_date, self.to_date)
		imports_of_goods = get_imports_of_goods(self.company, self.from_date, self.to_date)
		input_vat_credit = get_input_vat_credit(self.company, self.from_date, self.to_date)

		self.boxes = []
		for box_code, description, box in _build_box_rows(
			domestic_supplies, exports, reverse_charge_purchases, imports_of_goods, input_vat_credit
		):
			self.append(
				"boxes",
				{
					"box_code": box_code,
					"description": description,
					"taxable_amount": box["taxable_amount"],
					"vat_amount": box["vat_amount"],
					"adjustment_taxable_amount": box["adjustment_taxable_amount"],
					"adjustment_vat_amount": box["adjustment_vat_amount"],
				},
			)

		self.total_vat_due = get_total_vat_due(domestic_supplies, reverse_charge_purchases)
		self.input_vat_credit_total = get_input_vat_credit_total(input_vat_credit)
		self.net_tax_liability = get_net_tax_liability(self.total_vat_due, self.input_vat_credit_total)

		self.generated_for_company = self.company
		self.generated_for_from_date = self.from_date
		self.generated_for_to_date = self.to_date

		self.save()

	@frappe.whitelist()
	def mark_as_filed(self):
		"""The only supported Draft -> Filed transition (see validate_filed_is_immutable() above,
		which locks the document the moment this save lands). Requires boxes to already be
		generated — filing a return that was never run through generate_return() would lock in an
		all-zero return rather than the period's actual figures. The staleness check must happen
		here, before `status` is flipped, rather than being left to save()'s own
		_clear_boxes_if_stale(): that runs inside the same validate() call as
		validate_filed_is_immutable(), so relying on it alone would let a stale save wipe `boxes`
		to empty while `status` is already set to "Filed" in memory, persisting an all-zero Filed
		return instead of refusing the transition outright."""
		if self.status == "Filed":
			frappe.throw(_("This return has already been filed."))

		if not self.boxes:
			frappe.throw(_("Generate the return before filing it."))

		if self._boxes_are_stale():
			frappe.throw(
				_(
					"The generated boxes no longer match this return's Company/From Date/To Date. Regenerate the return before filing it."
				)
			)

		self.status = "Filed"
		self.save()


def _build_box_rows(domestic_supplies, exports, reverse_charge_purchases, imports_of_goods, input_vat_credit):
	"""Yields (box_code, description, box) tuples in official return order. 1(d)/1(e)/1(f) are
	always zero — no signal exists for profit-margin-scheme goods, and the intra-GCC supplies
	mechanism isn't activated by the OTA yet — but still appear as rows, not omitted, so the
	return's shape always mirrors the official 7-box form. Box 2(a) intra-GCC purchases *is*
	computed (`is_gcc_supplier` exists), unlike 1(d)/1(e)'s supply-side counterpart, but carries the
	same "not yet activated" caveat in its description, since the OTA hasn't turned the mechanism
	on for either side yet. Box 6 has no official sub-letters in the return form itself, but this
	app still reports its four required sub-splits (ordinary/imports/fixed assets/adjustments) as
	separate rows sharing box_code "6", since collapsing them would silently drop the very
	breakdown the box definition asks for."""
	yield "1(a)", _("Standard-rated domestic supplies"), domestic_supplies["standard_rated"]
	yield "1(b)", _("Zero-rated domestic supplies"), domestic_supplies["zero_rated"]
	yield "1(c)", _("Exempt domestic supplies"), domestic_supplies["exempt"]
	yield "1(d)", _("Intra-GCC supplies (not yet activated by the OTA)"), _EMPTY_BOX
	yield "1(e)", _("Intra-GCC supplies (not yet activated by the OTA)"), _EMPTY_BOX
	yield "1(f)", _("Profit-margin scheme goods (not yet supported by this app)"), _EMPTY_BOX
	yield (
		"2(a)",
		_("Intra-GCC reverse-charge purchases (not yet activated by the OTA)"),
		reverse_charge_purchases["gcc"],
	)
	yield "2(b)", _("Non-GCC reverse-charge purchases"), reverse_charge_purchases["non_gcc"]
	yield "3(a)", _("Exports"), exports
	yield "4(a)", _("Imports of goods with postponed payment"), imports_of_goods["postponed"]
	yield "4(b)", _("Total goods imported"), imports_of_goods["total"]
	yield "6", _("Input VAT credit — ordinary purchases"), input_vat_credit["ordinary"]
	yield "6", _("Input VAT credit — imports"), input_vat_credit["imports"]
	yield "6", _("Input VAT credit — fixed assets"), input_vat_credit["fixed_assets"]
	yield "6", _("Input VAT credit — adjustments"), input_vat_credit["adjustments"]
