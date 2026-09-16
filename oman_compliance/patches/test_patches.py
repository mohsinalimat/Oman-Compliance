import os

from frappe.tests.utils import FrappeTestCase

from oman_compliance.patches.v1.migrate_oman_vat_settings import execute


class TestPatches(FrappeTestCase):
	def test_migrate_oman_vat_settings_is_registered(self):
		patches_txt = os.path.join(os.path.dirname(__file__), "..", "patches.txt")
		with open(patches_txt) as f:
			content = f.read()

		self.assertIn("oman_compliance.patches.v1.migrate_oman_vat_settings", content)

	def test_execute_is_a_noop_when_legacy_app_not_installed(self):
		# This bench doesn't have oman_vat installed (the normal case for almost every real site) —
		# a genuine, always-available way to confirm the patch itself is a safe no-op, without
		# needing the legacy app's doctypes. migrate_oman_vat_settings()'s own fuller behavior
		# (unambiguous/ambiguous accounts, TRN migration, idempotency) is covered directly in
		# utils/test_migration.py, against a real DB-backed simulation of the legacy schema.
		execute()
