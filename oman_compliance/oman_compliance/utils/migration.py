import frappe
from frappe.query_builder import Case, DocType
from frappe.query_builder.functions import Count

from oman_compliance.oman_compliance.constants import DEFAULT_VAT_CATEGORY
from oman_compliance.oman_compliance.utils.company import is_oman_company
from oman_compliance.oman_compliance.utils.trn import validate_trn

LEGACY_APP = "oman_vat"

# The five child doctypes this app puts `vat_category` on today (constants/custom_fields.py).
# Legacy oman_vat also carried its is_zero_rated/is_exempt flags on POS Invoice Item, Purchase
# Order Item, Purchase Receipt Item, and Supplier Quotation Item, but this app never modeled VAT
# Category on those doctypes at all (a deliberate scope decision from earlier phases) — there's
# nothing on the oman_compliance side for that data to migrate into, so they're left alone here
# rather than inventing a field this app doesn't otherwise have.
ITEM_VAT_FLAG_DOCTYPES = {
	"Sales Order Item": "Sales Order",
	"Quotation Item": "Quotation",
	"Delivery Note Item": "Delivery Note",
	"Sales Invoice Item": "Sales Invoice",
	"Purchase Invoice Item": "Purchase Invoice",
}


def _legacy_app_installed() -> bool:
	return LEGACY_APP in frappe.get_installed_apps()


def migrate_oman_vat_settings() -> dict:
	"""One-time-per-company, idempotent migration from legacy oman_vat's `OMAN VAT Setting` (one
	document per company, each holding a list of (Item Tax Template, Account) rows for sales and
	purchase) into this app's `Oman VAT Settings.vat_accounts` (one row per company, a single
	Output/Input VAT Account each — see OMAN_COMPLIANCE_PLAN.md's Phase 6 entry for why the two
	shapes differ).

	Safe to run on every `bench migrate` (wired into patches.txt): no-ops entirely if oman_vat
	isn't installed, and never touches a company that already has a `vat_accounts` row (an admin's
	existing configuration is never overwritten). Only writes settings/master data — never touches
	a transactional document — so unlike migrate_legacy_item_vat_flags() below, this doesn't need
	to be an opt-in, manually-invoked utility.

	A legacy company's sales/purchase accounts collapse onto this app's single
	output_vat_account/input_vat_account only when every row on that side names the same account
	(per the user's explicit direction: auto-derive only when unambiguous, never guess). Companies
	where that doesn't hold — or whose legacy OMAN VAT Setting isn't actually for an Oman company
	(this app has been bitten before by cross-company leakage on a shared bench, see
	utils/company.py::is_oman_company()) — are skipped and reported under "needs_review" instead,
	along with any Company TRN that doesn't pass this app's stricter format validation (legacy
	never validated TRN format at all).

	Returns a summary dict for the caller (the patch, or a manual re-run) to report."""
	result = {"accounts_migrated": 0, "trns_migrated": 0, "needs_review": []}

	if not _legacy_app_installed():
		return result

	settings = frappe.get_single("Oman VAT Settings")
	already_configured = {row.company for row in settings.vat_accounts}

	for legacy in frappe.get_all("OMAN VAT Setting", fields=["name", "company"]):
		if legacy.company in already_configured:
			continue

		if not is_oman_company(legacy.company):
			result["needs_review"].append({"company": legacy.company, "reason": "company_not_oman"})
			continue

		sales_accounts = set(
			frappe.get_all(
				"OMAN VAT Sales Account",
				filters={"parenttype": "OMAN VAT Setting", "parent": legacy.name},
				pluck="account",
			)
		)
		purchase_accounts = set(
			frappe.get_all(
				"OMAN VAT Purchase Account",
				filters={"parenttype": "OMAN VAT Setting", "parent": legacy.name},
				pluck="account",
			)
		)

		if len(sales_accounts) != 1:
			result["needs_review"].append(
				{"company": legacy.company, "reason": "ambiguous_or_missing_output_vat_account"}
			)
			continue

		row = {"company": legacy.company, "output_vat_account": next(iter(sales_accounts))}
		if len(purchase_accounts) == 1:
			row["input_vat_account"] = next(iter(purchase_accounts))

		settings.append("vat_accounts", row)
		result["accounts_migrated"] += 1

	if result["accounts_migrated"]:
		settings.save(ignore_permissions=True)

	for company in frappe.get_all(
		"Company", filters={"country": "Oman"}, fields=["name", "tax_id", "oman_trn"]
	):
		if company.oman_trn or not company.tax_id:
			continue

		try:
			trn = validate_trn(company.tax_id, label="Company TRN")
		except frappe.ValidationError:
			result["needs_review"].append({"company": company.name, "reason": "invalid_legacy_trn"})
			continue

		frappe.db.set_value("Company", company.name, "oman_trn", trn)
		result["trns_migrated"] += 1

	return result


@frappe.whitelist()
def migrate_legacy_item_vat_flags(company: str | None = None) -> dict:
	"""One-time, explicitly-invoked backfill of `vat_category` on already-submitted (and draft)
	Sales Order/Quotation/Delivery Note/Sales Invoice/Purchase Invoice item rows, from legacy
	oman_vat's `is_zero_rated`/`is_exempt` Item flags — which is_zero_rated=1 → "Zero Rated",
	is_exempt=1 → "Exempt" (checked in that order), and anything else → DEFAULT_VAT_CATEGORY
	("Standard Rated"). That last branch isn't cosmetic: Phase 3's VAT Return section functions
	(utils/vat_return/sections/*.py) read `vat_category` directly, so a migrated row left blank
	would be silently miscategorized/excluded from a historical period's box totals, not merely
	"unlabeled".

	Deliberately NOT wired into patches.txt, for the exact reason
	utils/vat_return/backfill.py::backfill_classification_flags() gives for its own fields: this
	app never bulk-edits historical transactional documents from an automatic migration step, only
	reference/settings data. An admin adopting this migration should run this once, deliberately,
	e.g. via `bench execute
	oman_compliance.oman_compliance.utils.migration.migrate_legacy_item_vat_flags`.

	Implemented as one bulk UPDATE per child table (via the query builder, not raw SQL) rather
	than a per-row Python loop: unlike backfill_classification_flags()'s handful of header-level
	flags per document, this can touch every historical item row on a site.

	Restricted to System Manager, matching backfill_classification_flags(): this bypasses ordinary
	document permissions and can touch every submitted document's item rows on the site.

	Returns a count of rows changed per child doctype."""
	frappe.only_for("System Manager")

	result = {doctype: 0 for doctype in ITEM_VAT_FLAG_DOCTYPES}

	if not _legacy_app_installed():
		return result

	for doctype, parent_doctype in ITEM_VAT_FLAG_DOCTYPES.items():
		meta = frappe.get_meta(doctype)
		if not (meta.has_field("is_zero_rated") and meta.has_field("is_exempt")):
			continue

		item = DocType(doctype)
		condition = (item.vat_category.isnull()) | (item.vat_category == "")

		if company:
			parent = DocType(parent_doctype)
			matching_parents = frappe.qb.from_(parent).select(parent.name).where(parent.company == company)
			condition &= item.parent.isin(matching_parents)

		count = frappe.qb.from_(item).where(condition).select(Count("*")).run()[0][0]
		if not count:
			continue

		frappe.qb.update(item).set(
			item.vat_category,
			Case()
			.when(item.is_zero_rated == 1, "Zero Rated")
			.when(item.is_exempt == 1, "Exempt")
			.else_(DEFAULT_VAT_CATEGORY),
		).where(condition).run()

		result[doctype] = count

	return result
