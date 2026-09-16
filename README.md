### Oman Compliance

VAT compliance for ERPNext companies registered in Oman: TRN and Designated Zone masters, VAT Category
defaulting/validation on transactions, Reverse Charge and Import of Goods handling, a VAT Return with sales/
purchase registers, and Tax Invoice / Simplified Tax Invoice print formats with QR codes. Gated entirely on a
Company's **Country** being **Oman** — safe to install alongside unrelated companies' own apps on a shared
bench.

See `OMAN_COMPLIANCE_CONFIGURATION.md` for full setup/usage instructions, `OMAN_COMPLIANCE_PLAN.md` for what's
shipped vs. still pending, and `OMAN_COMPLIANCE_ARCHITECTURE.md` for the underlying design.

E-invoicing (Fawtara/PINT-OM) is intentionally not yet implemented — the OTA's own developer/API
documentation isn't confirmed available yet, and this isn't a pilot participant. See
`OMAN_COMPLIANCE_ARCHITECTURE.md` §3 for status.

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch main
bench install-app oman_compliance
```

Then configure the app for each Oman company — see "Suggested setup order for a new company" in
`OMAN_COMPLIANCE_CONFIGURATION.md`.

### Migrating from `oman_vat`

If a site already runs the older `oman_vat` app, this app can coexist with it — there's no requirement to
uninstall `oman_vat` first or ever.

- **Settings and TRN data migrate automatically.** Every `bench migrate` checks whether `oman_vat` is
  installed and, if so, copies each company's legacy `OMAN VAT Setting` (a list of per-Item-Tax-Template
  sales/purchase accounts) into this app's `Oman VAT Settings` → VAT Accounts (a single Output/Input VAT
  Account per company) — but only when a company's legacy accounts unambiguously agree on one account per
  side. A company already configured in `Oman VAT Settings` is never overwritten. Anything that can't be
  migrated automatically (an ambiguous account, a Company TRN that fails this app's stricter format check) is
  reported via the Error Log for manual review rather than guessed. Company TRNs are also copied from the
  legacy `tax_id` field into this app's own `oman_trn` field the same way.
- **Historical item-level VAT flags migrate on request, not automatically.** Legacy `is_zero_rated`/
  `is_exempt` Item flags don't map onto this app's `vat_category` field the same way — running the mapping
  automatically for every submitted invoice on every site's next migrate would be a much bigger, more
  surprising action than this app's other (settings-only) migrations. Run it once, deliberately, on a site
  with real historical data:

  ```bash
  bench execute oman_compliance.oman_compliance.utils.migration.migrate_legacy_item_vat_flags
  ```

  Pass `company="..."` to scope it to one company. This backfills `vat_category` on Sales Order/Quotation/
  Delivery Note/Sales Invoice/Purchase Invoice item rows still missing it — needed before Phase 3's VAT Return
  section functions will correctly categorize a historical period's totals.

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/oman_compliance
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

### CI

This app uses GitHub Actions for CI. The following workflows are configured:

- CI: Installs this app (alongside legacy `oman_vat`, to exercise the migration described above) and runs
  unit tests on every push to `main` and on every pull request.
- Linters: Runs [Frappe Semgrep Rules](https://github.com/frappe/semgrep-rules) and [pip-audit](https://pypi.org/project/pip-audit/) on every pull request.


### License

agpl-3.0
