import os
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from oman_compliance.patches.v1.migrate_oman_vat_settings import execute


class TestPatches(FrappeTestCase):
	def test_migrate_oman_vat_settings_is_registered(self):
		patches_txt = os.path.join(os.path.dirname(__file__), "..", "patches.txt")
		with open(patches_txt) as f:
			content = f.read()

		self.assertIn("oman_compliance.patches.v1.migrate_oman_vat_settings", content)

	def test_execute_is_a_noop_when_legacy_app_not_installed(self):
		# Mocked explicitly rather than relying on this bench's ambient installed-apps state: CI
		# genuinely installs oman_vat (to exercise utils/test_migration.py's fuller coverage for
		# real), so this is the only way to deterministically exercise the "not installed" no-op
		# branch there too.
		with (
			patch(
				"oman_compliance.oman_compliance.utils.migration.frappe.get_installed_apps",
				return_value=["frappe", "erpnext", "oman_compliance"],
			),
			patch("oman_compliance.patches.v1.migrate_oman_vat_settings.frappe.log_error") as log_error,
			patch("builtins.print") as mock_print,
		):
			execute()

		mock_print.assert_not_called()
		log_error.assert_not_called()
