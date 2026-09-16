from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from oman_compliance.oman_compliance.utils.migration import (
	migrate_legacy_item_vat_flags,
	migrate_oman_vat_settings,
)
from oman_compliance.tests import (
	create_submitted_sales_invoice,
	get_non_oman_test_company,
	get_oman_test_company,
	get_oman_test_vat_accounts,
	get_unique_test_date,
	set_vat_accounts,
)

# Both migrate_*() functions gate on the real `oman_vat` app being installed. This bench has its
# doctypes reloaded for real DB-backed testing (see OMAN_COMPLIANCE_PLAN.md's Phase 6 status log)
# without the app itself being installed, so only that specific check is mocked — and only for the
# duration of the call under test, never around fixture setup (create_submitted_sales_invoice,
# Company/Account creation, etc.), since frappe internals elsewhere legitimately depend on the real
# installed-apps list (e.g. hook resolution) and must see it unpatched.
_INSTALLED_APPS_WITH_LEGACY = ["frappe", "erpnext", "oman_compliance", "oman_vat"]
_INSTALLED_APPS_WITHOUT_LEGACY = ["frappe", "erpnext", "oman_compliance"]


def _migrate_settings(installed_apps=_INSTALLED_APPS_WITH_LEGACY):
	with patch(
		"oman_compliance.oman_compliance.utils.migration.frappe.get_installed_apps",
		return_value=installed_apps,
	):
		return migrate_oman_vat_settings()


def _migrate_item_flags(installed_apps=_INSTALLED_APPS_WITH_LEGACY, **kwargs):
	with patch(
		"oman_compliance.oman_compliance.utils.migration.frappe.get_installed_apps",
		return_value=installed_apps,
	):
		return migrate_legacy_item_vat_flags(**kwargs)


def _create_legacy_setting(company: str, sales_accounts: list[str], purchase_accounts: list[str]):
	# FrappeTestCase rolls back per-class, not per-test (see get_oman_test_company()'s own
	# docstring) — but "OMAN VAT Setting" is named by company (autoname="field:company"), so
	# sibling tests reusing the same test company would otherwise collide on a second insert.
	frappe.delete_doc("OMAN VAT Setting", company, force=True, ignore_permissions=True, ignore_missing=True)

	doc = frappe.get_doc(
		{
			"doctype": "OMAN VAT Setting",
			"company": company,
			"oman_vat_sales_accounts": [
				{"title": f"Sales {i}", "item_tax_template": "_Test Template", "account": account}
				for i, account in enumerate(sales_accounts)
			],
			"oman_vat_purchase_accounts": [
				{"title": f"Purchase {i}", "item_tax_template": "_Test Template", "account": account}
				for i, account in enumerate(purchase_accounts)
			],
		}
	)
	# Both child tables are `reqd` on the legacy doctype (a real legacy setting always had at least
	# one row each), but this migration must cope with whatever is actually in a legacy site's
	# database, not just well-formed data — ignore_mandatory lets tests construct the edge cases
	# (e.g. a missing purchase-account side) without fighting a validation legacy data may not have
	# actually been subject to (bulk imports, manual DB edits, etc.).
	return doc.insert(ignore_permissions=True, ignore_links=True, ignore_mandatory=True)


class TestMigrateOmanVatSettings(FrappeTestCase):
	def setUp(self):
		self.company = get_oman_test_company()
		output_account, input_account = get_oman_test_vat_accounts(self.company)
		self.output_account = output_account
		self.input_account = input_account

		# FrappeTestCase rolls back per-class, not per-test, and Oman VAT Settings is a Single —
		# without this, a row a sibling test method appended for the same test company would still
		# be sitting there when this test's setUp runs, so migrate_oman_vat_settings()'s
		# already-configured check would (correctly) skip it, hiding this test's own scenario.
		settings = frappe.get_single("Oman VAT Settings")
		settings.vat_accounts = [r for r in settings.vat_accounts if r.company != self.company]
		settings.save(ignore_permissions=True)

		# Same per-class-rollback reasoning for the Company-level TRN fields a sibling test method
		# may have left set on this same shared test company.
		frappe.db.set_value("Company", self.company, {"tax_id": "", "oman_trn": ""})

	def test_migrates_unambiguous_accounts(self):
		_create_legacy_setting(self.company, [self.output_account], [self.input_account])

		result = _migrate_settings()

		settings = frappe.get_single("Oman VAT Settings")
		row = next(r for r in settings.vat_accounts if r.company == self.company)
		self.assertEqual(row.output_vat_account, self.output_account)
		self.assertEqual(row.input_vat_account, self.input_account)
		self.assertEqual(result["accounts_migrated"], 1)
		self.assertEqual(result["needs_review"], [])

	def test_ambiguous_sales_accounts_are_flagged_not_guessed(self):
		other_account, _ = get_oman_test_vat_accounts(get_non_oman_test_company())
		_create_legacy_setting(self.company, [self.output_account, other_account], [self.input_account])

		result = _migrate_settings()

		settings = frappe.get_single("Oman VAT Settings")
		self.assertFalse(any(r.company == self.company for r in settings.vat_accounts))
		self.assertEqual(result["accounts_migrated"], 0)
		self.assertEqual(
			result["needs_review"],
			[{"company": self.company, "reason": "ambiguous_or_missing_output_vat_account"}],
		)

	def test_ambiguous_purchase_account_leaves_input_account_blank_and_flags_for_review(self):
		other_account, _ = get_oman_test_vat_accounts(get_non_oman_test_company())
		_create_legacy_setting(self.company, [self.output_account], [self.input_account, other_account])

		result = _migrate_settings()

		settings = frappe.get_single("Oman VAT Settings")
		row = next(r for r in settings.vat_accounts if r.company == self.company)
		self.assertEqual(row.output_vat_account, self.output_account)
		self.assertFalse(row.input_vat_account)
		self.assertEqual(result["accounts_migrated"], 1)
		self.assertIn(
			{"company": self.company, "reason": "ambiguous_or_missing_input_vat_account"},
			result["needs_review"],
		)

	def test_missing_purchase_accounts_flags_for_review(self):
		_create_legacy_setting(self.company, [self.output_account], [])

		result = _migrate_settings()

		settings = frappe.get_single("Oman VAT Settings")
		row = next(r for r in settings.vat_accounts if r.company == self.company)
		self.assertFalse(row.input_vat_account)
		self.assertEqual(result["accounts_migrated"], 1)
		self.assertIn(
			{"company": self.company, "reason": "ambiguous_or_missing_input_vat_account"},
			result["needs_review"],
		)

	def test_never_overwrites_an_already_configured_company(self):
		set_vat_accounts(self.company, output_account=self.output_account)
		_create_legacy_setting(self.company, [self.input_account], [])

		result = _migrate_settings()

		settings = frappe.get_single("Oman VAT Settings")
		row = next(r for r in settings.vat_accounts if r.company == self.company)
		self.assertEqual(row.output_vat_account, self.output_account)
		self.assertEqual(result["accounts_migrated"], 0)
		self.assertEqual(result["needs_review"], [])

	def test_non_oman_company_setting_is_flagged(self):
		other_company = get_non_oman_test_company()
		_create_legacy_setting(other_company, [self.output_account], [])

		result = _migrate_settings()

		self.assertIn({"company": other_company, "reason": "company_not_oman"}, result["needs_review"])

	def test_migrates_valid_legacy_trn(self):
		frappe.db.set_value("Company", self.company, "tax_id", "OM1234567890")
		frappe.db.set_value("Company", self.company, "oman_trn", "")

		result = _migrate_settings()

		self.assertEqual(frappe.db.get_value("Company", self.company, "oman_trn"), "OM1234567890")
		self.assertEqual(result["trns_migrated"], 1)

	def test_invalid_legacy_trn_is_flagged_not_thrown(self):
		frappe.db.set_value("Company", self.company, "tax_id", "not-a-real-trn")
		frappe.db.set_value("Company", self.company, "oman_trn", "")

		result = _migrate_settings()

		self.assertFalse(frappe.db.get_value("Company", self.company, "oman_trn"))
		self.assertIn({"company": self.company, "reason": "invalid_legacy_trn"}, result["needs_review"])

	def test_existing_oman_trn_is_never_overwritten(self):
		frappe.db.set_value("Company", self.company, "tax_id", "OM1234567890")
		frappe.db.set_value("Company", self.company, "oman_trn", "OM9999999999")

		result = _migrate_settings()

		self.assertEqual(frappe.db.get_value("Company", self.company, "oman_trn"), "OM9999999999")
		self.assertEqual(result["trns_migrated"], 0)

	def test_is_idempotent(self):
		_create_legacy_setting(self.company, [self.output_account], [self.input_account])

		_migrate_settings()
		second_run = _migrate_settings()

		self.assertEqual(second_run["accounts_migrated"], 0)
		settings = frappe.get_single("Oman VAT Settings")
		self.assertEqual(sum(1 for r in settings.vat_accounts if r.company == self.company), 1)

	def test_noop_when_legacy_app_not_installed(self):
		# Mocked explicitly rather than relying on this bench's ambient installed-apps state: CI
		# genuinely installs oman_vat (to exercise the rest of this test class for real), so this
		# is the only way to deterministically exercise the "not installed" branch there too.
		_create_legacy_setting(self.company, [self.output_account], [self.input_account])

		result = _migrate_settings(installed_apps=_INSTALLED_APPS_WITHOUT_LEGACY)

		self.assertEqual(result, {"accounts_migrated": 0, "trns_migrated": 0, "needs_review": []})


class TestMigrateLegacyItemVatFlags(FrappeTestCase):
	def setUp(self):
		self.company = get_oman_test_company()
		self.test_date = get_unique_test_date()

		# FrappeTestCase rolls back per-class, not per-test: a sibling test method may have left a
		# blank-vat_category row behind for this same shared test company (e.g. one deliberately
		# created but never migrated, to test the no-op-when-not-installed case). Sweep those away
		# first so each test method only ever sees the row(s) it creates for itself.
		_migrate_item_flags(company=self.company)

	def _legacy_row(self, is_zero_rated=0, is_exempt=0, vat_category="", company=None):
		invoice = create_submitted_sales_invoice(
			company or self.company,
			vat_category="Standard Rated",
			net_amount=100,
			posting_date=self.test_date,
		)
		row = invoice.items[0]
		frappe.db.set_value(
			"Sales Invoice Item",
			row.name,
			{"is_zero_rated": is_zero_rated, "is_exempt": is_exempt, "vat_category": vat_category},
		)
		return row.name

	def test_zero_rated_flag_backfills_zero_rated_category(self):
		row_name = self._legacy_row(is_zero_rated=1)

		result = _migrate_item_flags(company=self.company)

		self.assertEqual(frappe.db.get_value("Sales Invoice Item", row_name, "vat_category"), "Zero Rated")
		self.assertEqual(result["Sales Invoice Item"], 1)

	def test_exempt_flag_backfills_exempt_category(self):
		row_name = self._legacy_row(is_exempt=1)

		_migrate_item_flags(company=self.company)

		self.assertEqual(frappe.db.get_value("Sales Invoice Item", row_name, "vat_category"), "Exempt")

	def test_neither_flag_backfills_default_category(self):
		row_name = self._legacy_row()

		_migrate_item_flags(company=self.company)

		self.assertEqual(
			frappe.db.get_value("Sales Invoice Item", row_name, "vat_category"), "Standard Rated"
		)

	def test_already_categorized_row_is_left_untouched(self):
		row_name = self._legacy_row(is_zero_rated=1, vat_category="Exempt")

		_migrate_item_flags(company=self.company)

		self.assertEqual(frappe.db.get_value("Sales Invoice Item", row_name, "vat_category"), "Exempt")

	def test_company_filter_excludes_other_companies(self):
		other_company = get_non_oman_test_company()
		row_name = self._legacy_row(is_zero_rated=1)

		result = _migrate_item_flags(company=other_company)

		self.assertEqual(result["Sales Invoice Item"], 0)
		self.assertEqual(frappe.db.get_value("Sales Invoice Item", row_name, "vat_category"), "")

	def test_sitewide_run_still_excludes_non_oman_companies(self):
		other_company = get_non_oman_test_company()
		oman_row = self._legacy_row(is_zero_rated=1)
		other_row = self._legacy_row(is_zero_rated=1, company=other_company)

		# No `company` argument at all — a real "run once for every Oman company" invocation, not
		# scoped to one company. Must still never touch a non-Oman company's data, the same way
		# every other transaction-level behavior in this app is gated on utils/company.py::
		# is_oman_company(), even though nothing here filters to `self.company` specifically.
		_migrate_item_flags()

		self.assertEqual(frappe.db.get_value("Sales Invoice Item", oman_row, "vat_category"), "Zero Rated")
		self.assertEqual(frappe.db.get_value("Sales Invoice Item", other_row, "vat_category"), "")

	def test_is_idempotent(self):
		self._legacy_row(is_zero_rated=1)

		_migrate_item_flags(company=self.company)
		second_run = _migrate_item_flags(company=self.company)

		self.assertEqual(second_run["Sales Invoice Item"], 0)

	def test_noop_when_legacy_app_not_installed(self):
		# Mocked explicitly rather than relying on this bench's ambient installed-apps state — see
		# the same note on TestMigrateOmanVatSettings.test_noop_when_legacy_app_not_installed.
		self._legacy_row(is_zero_rated=1)

		result = _migrate_item_flags(installed_apps=_INSTALLED_APPS_WITHOUT_LEGACY, company=self.company)

		self.assertEqual(result["Sales Invoice Item"], 0)
