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

### Configuration checklist: generating a VAT Return

An **Oman VAT Return** can only be generated correctly once, for the company in question, all of the
following are in place. `OMAN_COMPLIANCE_CONFIGURATION.md` covers the reasoning behind each in full; this is
the minimum checklist:

1. **Company TRN** — set the Company's **TRN** field (Desk → Company).
2. **Oman VAT Settings → VAT Accounts** — add a row for the company naming its **Output VAT Account**
   (required) and **Input VAT Account** (required only if the company uses Reverse Charge). Without this row,
   VAT Category validation and Reverse Charge can't identify which ledger rows are actually VAT.
3. **VAT Category on Item Tax Templates** — set each Oman tax template's own **VAT Category** (Standard
   Rated/Zero Rated/Exempt/Out of Scope) so transactions using it default and validate correctly, rather than
   relying only on the zone-based fallback.
4. **Designated Zone tagging** — link any **Address** inside Duqm (SEZAD), Salalah, Sohar, or Al Mazunah to
   its **Designated Zone**, so Zero Rated auto-defaults on transactions delivered there.
5. **Reverse Charge Applicable** (Purchase Invoice, box 2) — for imported services, check this and use a
   Purchase Taxes and Charges template that posts both a self-accounted output VAT row (to the Output VAT
   Account) and an offsetting input VAT row (to the Input VAT Account).
6. **Dispatch Address** (Purchase Invoice, box 4 — imports of goods) — set on cross-border purchases so
   **Import of Goods** is detected automatically from its country vs. the Company's own.
7. **Shipping/Customer Address** (Sales Invoice, box 3(a) exports vs. box 1(b) domestic zero-rated) — set to
   the actual delivery country so **Export** is detected automatically.
8. **Supplier Address** (Purchase Invoice, box 2(a)/2(b) GCC vs. non-GCC reverse charge) — set so **GCC
   Supplier** is detected automatically from its country.

Once a company is configured, generate a return from Desk → **Oman VAT Return** → New: set **Company**,
**From Date**, **To Date**, then click **Generate Return** to recompute every box from that period's
transactions. A return can be regenerated freely while **Status** is Draft (e.g. after correcting an
invoice); setting it to Filed locks it permanently.

If a site has historical data from `oman_vat`, also run the one-time backfill described in "Migrating from
`oman_vat`" below before generating a return that covers pre-migration periods.

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
  Delivery Note/Sales Invoice/Purchase Invoice item rows still missing it — needed before the VAT Return
  section functions will correctly categorize a historical period's totals.

#### Recommendation: remove `oman_vat` once migration is verified

Coexistence is meant as a safety net for a live cutover, not a permanent state. `oman_vat` was audited and
found to implement only a decorative QR code and a two-section sales/purchase ledger — no real 7-box VAT
return, no reverse charge, no designated-zone handling, no e-invoicing path, and an active bug that reports
document-currency amounts as if they were OMR (see `OMAN_VAT_COMPLIANCE_FINDINGS.md`). Leaving it installed
after cutover risks someone running its inaccurate report, or editing its settings, by mistake.

Once you've:

1. Installed `oman_compliance` and run `bench migrate` (auto-migrates Oman VAT Settings and TRNs),
2. Confirmed each company's **Oman VAT Settings** and **Company TRN** migrated correctly — check the Error
   Log for anything flagged for manual review, and fix those by hand,
3. Run the one-time `migrate_legacy_item_vat_flags` backfill above against real historical data, and
4. Generated at least one **Oman VAT Return** in `oman_compliance` and spot-checked its totals against
   `oman_vat`'s old report for the same period,

remove `oman_vat` from the site:

```bash
bench --site $SITE uninstall-app oman_vat
bench remove-app oman_vat   # optional: also drop it from the bench entirely
```

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
