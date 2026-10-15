# Contract — the migration register

**Owner:** Developer 1 · **Config:** `backend/alembic.ini` · **Head today:** `onboarding_0060_drop_retired`

The prototype's migrations, from four developers and one platform change, in one
chain. This is the running order and the rules. Dev 1 keeps it current.

---

## 1. The register

Numbers are labels, not order (§2): the **Parent** column is the order. Every row is
merged.

| No. | Owner | Change | Parent |
|---|---|---|---|
| 0013 | Dev 1 | Generalise the history table: `dimension`, `deal_id`, `reason`, two indexes | `onboarding_0012_risk_critical` |
| 0014 | Dev 2 | Fresh company record: name, country, identifiers, marker, PAN unique, several GSTINs; real links from contacts, activities, screening items **and history**. Refuses to empty CRM tables that hold rows unless `E9_ALLOW_CRM_RESET=1` | `onboarding_0013_shared_history` |
| 0017 | Dev 2 | Qualification criteria, results and outcomes; the `journey` (3 values) and `qualification` columns | `onboarding_0014_company_record` |
| 0020 | Dev 2 | Retire the ten-status `lifecycle_status` | `onboarding_0017_qualification` |
| 0016 | Dev 3A | The conversation gauge and its check-back date; follow-up completion (locked) | `onboarding_0020_retire_lifecycle` |
| 0018 | Dev 3B | Deal and buyer | `onboarding_0016_engagement` |
| 0019 | Dev 3B | Documents | `onboarding_0018_deal_buyer` |
| 0015 | Dev 4A | The background-check gauge, locked superseding decisions, evidence snapshots, the CRM risk type | `onboarding_0019_documents` |
| `auth_0003` | Platform (user management) | User administration | `onboarding_0015_bg_check` |
| `auth_0004` | Platform (user management) | Roles and permissions as data (RBAC) | `auth_0003_user_admin` |
| 0021 | Dev 4B | Superseding verification reviews, the outcome freeze, evidence and subject snapshots | `auth_0004_rbac` |
| 0022 | Release audit | Database guards: no document or verification result is deleted, a document's identity is fixed once set, and a `HANDED_OVER` or `WITHDRAWN` deal no longer changes | `onboarding_0021_verif_review` |
| 0023 | Dev 1 | `onboarding_0023_compliance_core`: `verification_result.subject_company_id` (FK, set once then frozen by `trg_verification_result_input_immutability`); `exporter_profile.background_check_expires_at` (indexed). Downgrade lossy since later code writes both (drops every result's subject company and every current expiry; both re-derivable) — verified 1 Oct 2026 by a downgrade to 0022 and upgrade on a copy of the test database | `onboarding_0022_integrity` |
| 0024 | Dev 1 | `onboarding_0024_screen_evidence`: `screening_review_item.evidence_refs` (`jsonb NOT NULL DEFAULT '[]'`, DDL — no row updated). Lossy downgrade (drops the references) | `onboarding_0023_compliance_core` |
| 0025 | Dev 1 | `onboarding_0025_check_cycle`: append-only `check_cycle`; `cycle_id` on results, screening answers and decisions (composite FK on the last two), frozen on results; `background_check_decision.rules_version`; **inserts** one cycle 1 per company with inputs — no existing row updated (`NULL` cycle = cycle 1, `NULL` rules = v1). Lossy downgrade | `onboarding_0024_screen_evidence` |
| 0026 | Dev 1 | `onboarding_0026_maker_checker`: maker-checker — append-only `background_check_proposal` and `background_check_proposal_resolution` (one per proposal; `(outcome = 'WITHDRAWN') = (created_by = proposed_by)`, the proposer copy pinned by a composite FK); `background_check_decision.proposal_id`, `approved_by`, `approved_at` with `CHECK (approved_by IS NULL OR approved_by <> decided_by)` and a composite FK to the proposal (same company, proposer and move). Schema only, no data. Lossy downgrade (proposals and approvals) | `onboarding_0025_check_cycle` |
| 0027 | Dev 1 | `onboarding_0027_clear_expiry`: `background_check_decision.expires_at` (`CHECK`: CLEAR only, after `decided_at`); **data: backfills `exporter_profile.background_check_expires_at`** for every company now `CLEAR` from its last CLEAR decision (stored expiry, else `decided_at` + 8,760 h), only where NULL, idempotent; no append-only row touched. Dry run: `python -m app.modules.onboarding.migrations.onboarding_0027_clear_expiry --dry-run`; after: `--validate` must print 0. `pg_dump` first. Lossy downgrade (drops the stored expiries; sets the profile column back to NULL) | `onboarding_0026_maker_checker` |
| 0028 | Dev 2 | `onboarding_0028_deal_foundation`: the deal's new columns — `buyer_company_id` (FK to `exporter_profile.customer_id`, `RESTRICT`, with `ck_deal_buyer_is_not_the_seller`), `handover_snapshot` (`jsonb`), `seller_gst_registration_id` (FK to `exporter_gstin.id`, `RESTRICT`). Schema only, no data. Downgrade drops the three columns | `onboarding_0027_clear_expiry` |
| 0029 | Dev 2 | `onboarding_0029_deal_snapshot`: **data: backfills `deal.handover_snapshot`** for every `HANDED_OVER` deal without one, from its `deal_buyer` row and its handover history row (`snapshot_source = 'backfilled_from_deal_buyer'`; `buyer` / `document_ids` are `null` where that record no longer exists), **then** replaces `prevent_terminal_deal_change()` so the column is set once and never changed. No append-only row touched. Run the module's `_VALIDATION` queries before and after; the first must print 0 afterwards. `pg_dump` first. Downgrade restores 0022's function and clears only the backfilled snapshots | `onboarding_0028_deal_foundation` |
| 0030 | Dev 2 | `onboarding_0030_deal_req_docs`: `deal_required_document` (versioned, append-only, reuses 0019's `crm_document_category_enum`), **seeded with one `PRE_SHIPMENT` requirement. Changes behaviour:** from this revision a deal with no `AVAILABLE` pre-shipment document cannot be handed over, so open deals on a live database need one uploaded first; deals already handed over are not re-judged. Lossy downgrade (drops the record of what was required when) | `onboarding_0029_deal_snapshot` |
| 0031 | Dev 3 | `onboarding_0031_domestic_first`: **data:** the next version of `export_history` and `export_licence`, copied from the current one with `required = false` (none where the current version is already not required; `created_by = migration:onboarding_0031_domestic_first`), and `no_export_history`, `no_export_licence`, `geography_not_supported` deactivated. **Changes behaviour:** export results stop counting towards the suggestion, so an undecided lead may now read QUALIFIED; decided companies are not re-judged. `pg_dump` first. Downgrade deletes only its own rows and is refused once a result has been recorded against them (restore the dump instead) | `onboarding_0030_deal_req_docs` |
| `auth_0005` | Dev 3 | `auth_0005_rm_role_name`: **data:** the built-in OPERATIONS row in `auth.role` is named "RM (Relationship Manager)" and loses the "unless you own the record" description (decision 12) — only where an administrator has not already changed them. Slug and enum unchanged. Downgrade restores both | `onboarding_0031_domestic_first` |
| 0032 | Dev 3 | Company identity and pipeline status: `identity_type`, `registration_number`, `pipeline_status`, `created_via`, `created_via_deal_id`; `ExporterSource.DEAL_BUYER`; the not-in-pipeline check and the normalised registration-number unique index | `auth_0005_rm_role_name` |
| 0033 | Dev 3 | `onboarding_0033_created_via`: **data: backfills `exporter_profile.created_via`** from each company's earliest creation history row (`journey`, or `pipeline` for a buyer-only company), with the same source → channel mapping `domain/company_identity.py` applies to new companies — a test asserts the two agree. Also normalises any `created_via` already written to upper case (F3 shipped `'deal_buyer'`). Unmapped or missing sources stay `NULL` and are **reported as a count** rather than guessed as `MANUAL`. No append-only row touched. `pg_dump` first. Downgrade sets the column back to `NULL` for every company — lossless in that re-running reproduces it from the history rows, but it discards values written by a create path since | `onboarding_0032_company_identity` |
| 0034 | Dev 2 | `onboarding_0034_deal_buyer_co`: `deal.buyer_company_id` becomes **set once** (`trg_deal_buyer_company_set_once`, via `prevent_field_mutation_when_set` — `NULL` → a value is allowed once, so the buyer migration can still fill it) and is added to `prevent_terminal_deal_change()`, so a closed deal's buyer no longer changes. Schema only, no data. Downgrade drops the trigger and restores 0022's function body | `onboarding_0033_created_via` |
| 0035 | Dev 3 | `onboarding_0035_gst_branch`: `exporter_gstin` becomes a **branch record** (extended in place rather than copied to a new table) — `state_code`, `state_name`, `status`, `address`, `flag_status`, `flag_reason`, `active`, `deactivated_at/by`; `uq_exporter_gstin_id_customer_id` (exists to be referenced: it is what lets 0036's composite FK tie a deal's branch to its seller); checks for a flag's reason and for deactivation; **`trg_exporter_gstin_no_delete` refuses DELETE** — dropping a registration is now a deactivation, and `cascade="all, delete-orphan"` came off `gstin_rows` in the same task. **Data:** `state_code` from each GSTIN's first two characters and `state_name` from the code, with the same mapping `domain/gst_states.py` applies going forward (a test asserts they agree); **unknown codes keep `state_name NULL` and are reported as a count**. `pg_dump` first. Lossy downgrade (every address, status, flag and deactivation) and it re-enables deleting rows a deal may point at | `onboarding_0034_deal_buyer_co` |
| 0036 | Dev 2 | `onboarding_0036_deal_branch`: `deal.seller_gst_registration_id`'s FK becomes **composite** — `(seller_gst_registration_id, company_id)` → `(exporter_gstin.id, customer_id)` — so the database refuses a deal invoiced through another company's branch; and the column joins `prevent_terminal_deal_change()`. Settable and **changeable** before handover, unlike `buyer_company_id`'s set-once rule. Restates 0022's columns, 0029's snapshot block and 0034's `buyer_company_id`, because `CREATE OR REPLACE FUNCTION` keeps nothing. Schema only, no data. Downgrade restores 0028's single-column FK and 0034's function body | `onboarding_0035_gst_branch` |
| 0037 | Dev 3 | `onboarding_0037_trade_history`: `trade_relationship` (unique ordered pair, seller ≠ buyer — **no column on `deal`**), `trade_invoice` (identity frozen by `trg_trade_invoice_identity_immutability`; `deal_id` nullable for past trade; currency stored and never converted) and `trade_invoice_outcome` (append-only superseding chain via `public.prevent_mutation()`, one head per invoice and one superseder per row, so the chain is a line not a tree). Every table carries `created_by`/`source`/`source_ref`. Schema only; the relationship backfill is a command and runs separately. Lossy downgrade (everything recorded about past trade) | `onboarding_0036_deal_branch` |
| 0038 | Dev 2 | `onboarding_0038_buyer_map`: `deal_buyer_company_map` — one append-only row per legacy `deal_buyer`, keyed on `deal_buyer_id` as its **primary key** (which is what makes re-running the buyer migration a no-op), carrying `company_id`, `match_rule` (`buyer_match_rule_enum`: PAN, REGISTRATION_NUMBER, NEW, NAME_CONFIRMED — the last says a person decided), `matched_by`, `matched_at` and `run_id`. Mutation refused by `public.prevent_mutation()`. Schema only; the migration itself is a command, not a revision, because a person confirms the name-only duplicates. Lossy downgrade (the record of what each run decided) | `onboarding_0037_trade_history` |
| 0039 | Dev 2 | `onboarding_0039_closed_buyer`: `deal.buyer_company_id` moves out of `prevent_terminal_deal_change()`'s "any difference" list into its own `OLD.buyer_company_id IS NOT NULL` clause, so a **closed** deal's buyer company can be filled in once and never changed — 0029's precedent for `handover_snapshot`, which `buyer_company_id` had not been given. Without it §17.2 could not link a deal handed over before the migration, and its buyer's trade history and compliance results would stay unreachable from the deal that produced them. Found by writing 2.6's tests. Restates 0022's columns, 0029's snapshot block and 0036's branch column. Schema only. Downgrade restores 0036's body — **do not downgrade with a buyer migration pending**: terminal deals become permanently unlinkable | `onboarding_0038_buyer_map` |
| 0040 | Dev 3 | `onboarding_0040_iec_format`: `ck_exporter_profile_iec_format` — `iec IS NULL OR iec ~ '^[A-Z0-9]{10}$'`, the rule `IEC_RE` has always enforced in the service, restated as SQL so a bulk import, a fixture or a hand-written `UPDATE` cannot write past it. PAN, GSTIN, CIN and country have had such a check since 0014; the IEC was the one that did not. **No data**: written only after confirming `count(*) WHERE iec IS NOT NULL AND iec !~ '^[A-Z0-9]{10}$'` is 0 — were it not, this would have to be expand → backfill → contract, since adding a `CHECK` to a table with violating rows fails outright. Downgrade drops the constraint, losing nothing | `onboarding_0039_closed_buyer` |
| 0041 | Dev 2 | `onboarding_0041_map_rule_link`: `buyer_match_rule_enum` gains `ALREADY_LINKED` — the legacy row maps to the company it was already linked to before the buyer migration ran: its deal names it or its BUYER results already have it as their `subject_company_id`. Both links are set once, so the row can map nowhere else, and none of 0038's four values says so truthfully. **No data.** Postgres cannot drop an enum value, so the downgrade rebuilds the type without it, and **refuses** while any mapping row uses it — restore the dump taken before that run instead | `onboarding_0040_iec_format` |
| 0042 | Dev 3 | `onboarding_0042_deal_fks`: `fk_trade_invoice_deal_id` (`trade_invoice.deal_id`) and `fk_exporter_profile_created_via_deal_id` (`exporter_profile.created_via_deal_id`), both to `deal.id`, `ON DELETE RESTRICT` — they had been bare uuids, so an invoice could name a deal that never existed and keep it (`deal_id` is frozen once set). Each is added `NOT VALID` and validated only when no existing row violates it; otherwise it stays `NOT VALID` (enforced on every new or changed row) and the migration prints the count and the query that lists the rows. Copies of real data had none; databases built by the test suite do. Downgrade drops both, losing nothing | `onboarding_0041_map_rule_link` |
| 0043 | Dev 3 | `onboarding_0043_identity_type`: **data**. Recomputes `identity_type` where it disagrees with `pan` / `registration_number` (`decide_identity_type`'s rule in SQL), for companies edited before `update_profile` recomputed it; prints the count. No history row (the column is derived, as on create). Downgrade changes nothing: the old values were wrong by the rule every write path applies | `onboarding_0042_deal_fks` |
| 0044 | CRM | `onboarding_0044_assignment`: who works on a company — `ix_exporter_profile_rm_user` (partial) for the relationship manager's `relationship_manager_user_id`; `background_check_reviewer_id` and `background_check_reviewer_assigned_at` (both set or both null; a reviewer only while the check is `IN_REVIEW` or `MORE_INFO`) with `ix_exporter_profile_reviewer`. `ck_background_check_proposal_resolution_who` relaxed: the proposer never approves or rejects their own proposal, and who may withdraw is the service's rule. No data (the old RM text is matched by `backfill_relationship_managers`). Downgrade drops the columns and indexes and restores the stricter check; it fails if a withdrawal by someone other than the proposer exists | `onboarding_0043_identity_type` |
| `auth_0006` | CRM | `auth_0006_assignment_perms`: ADMIN is granted `exporters:assign_rm`, `compliance:assign` and `compliance:approve_high_risk` (`ON CONFLICT DO NOTHING`) | `onboarding_0044_assignment` |
| `auth_0007` | CRM | `auth_0007_business_permissions`: every CRM route checks a permission. New permissions (`settings:manage`, `exporters:partner_intake`, `deals:*`, `documents:view/upload/download`, `qualification:record`, `compliance:view/decide/approve`); the administrator becomes read-only; grants no route honoured are removed; the *Compliance lead* and *Sales lead* roles are seeded. Removals apply to a built-in role only while its grants are still as seeded; an edited one is named in the output for review | `auth_0006_assignment_perms` |
| 0045 | CRM | `onboarding_0045_doc_previews`: `crm_document.preview_status` (`READY` / `UNAVAILABLE`, `NULL` until tried) and `preview_storage_key` (set exactly when `READY`); outside the identity trigger | `auth_0007_business_permissions` |
| 0046 | CRM | `onboarding_0046_contact_status`: a contact's status (`ACTIVE`, `INACTIVE`, `LEFT_COMPANY`) with when and why it changed, and when and by whom it was last verified; `ck_exporter_contact_primary_is_active` | `onboarding_0045_doc_previews` |
| 0047 | CRM | `onboarding_0047_addresses`: `company_address` (typed, one active default per type, `trg_company_address_no_delete`) and `exporter_gstin.address_id`, a composite FK so a branch can only name its own company's address | `onboarding_0046_contact_status` |
| 0048 | CRM | `onboarding_0048_bank_accounts`: `company_bank_account`, one row per version of an account (`PENDING_APPROVAL` → `PENDING_VERIFICATION` → `VERIFIED`, or `REJECTED`; then `INACTIVE`); account number and IBAN encrypted, last four apart; one primary per currency, verified only | `onboarding_0047_addresses` |
| `auth_0008` | CRM | `auth_0008_bank_permissions`: `exporters:manage_bank_accounts`, `exporters:approve_bank_accounts`, `exporters:view_bank_details`. Additions only | `onboarding_0048_bank_accounts` |
| 0049 | CRM | `onboarding_0049_payment_terms`: versioned `payment_term` (seeded); `exporter_profile.default_payment_term_id`; `deal.value_amount`, `currency`, `payment_term_id`, `payment_term_override_reason`, which join the closed-deal freeze (`prevent_terminal_deal_change()` restated whole) | `auth_0008_bank_permissions` |
| 0050 | CRM | `onboarding_0050_collector`: `exporter_profile.collections_owner_user_id`, indexed | `onboarding_0049_payment_terms` |
| `auth_0009` | CRM | `auth_0009_collector_permission`: `exporters:assign_collector` for COMPLIANCE and every role that may assign RMs. Additions only | `onboarding_0050_collector` |
| 0051 | CRM | `onboarding_0051_company_groups`: `exporter_profile.parent_company_id` and `group_relationship`, set together, never the company itself; `trg_exporter_profile_no_group_cycle` refuses a loop | `auth_0009_collector_permission` |
| 0052 | CRM | `onboarding_0052_sanctions`: structured screening — versioned `sanctions_list` (seeded: UN Security Council, MHA / UAPA), `sanctions_run`, `sanctions_run_list`, append-only `sanctions_hit` and `sanctions_disposition` (a changed decision supersedes the previous one) | `onboarding_0051_company_groups` |
| `auth_0010` | CRM | `auth_0010_true_match_permission`: `compliance:approve_true_match`, for the Compliance lead and any role that approves high-risk Clears | `onboarding_0052_sanctions` |
| 0053 | CRM | `onboarding_0053_auto_criteria`: `qualification_criterion.auto_source` — where an automatic answer comes from; set on a new version; existing versions answer nothing automatically | `auth_0010_true_match_permission` |
| 0054 | Schema audit | `onboarding_0054_integrity_fks`: links and derived values the database now checks — FK `background_check_evidence.verification_review_id`; FK `exporter_lifecycle_history.deal_id`; `sanctions_run` and `verification_result` cycles must be their own company's (composite FKs; the result keeps its plain FK too); `sanctions_hit (run_id, list_code)` → the run's lists; `follow_up_completion (activity_id, customer_id)` → `exporter_activity` (new `uq_exporter_activity_id_customer`); CHECKs that `identity_type` follows `pan` / `registration_number` and `state_code = left(gstin, 2)`. **No data**: each rule is added `NOT VALID` and validated only when no row breaks it, else the count and listing query are printed (0042's pattern). Downgrade drops them and restores the two single-column FKs; nothing is lost | `onboarding_0053_auto_criteria` |
| 0055 | Schema audit | `onboarding_0055_config_freeze`: an old version of a payment term or a sanctions list never changes — `prevent_field_mutation_when_set` on every column but `is_current` and `updated_at` (`trg_payment_term_version_immutability`, `trg_sanctions_list_version_immutability`), as `qualification_criterion` and `deal_required_document` already are by being append-only. No data. Downgrade drops both triggers | `onboarding_0054_integrity_fks` |
| 0056 | Schema audit | `onboarding_0056_buyer_map_cols`: the buyer migration's answer moves onto `deal_buyer` — `mapped_company_id` (FK, `RESTRICT`), `match_rule` (`buyer_match_rule_enum`, kept), `matched_by`, `matched_at`, `mapping_run_id`; `ck_deal_buyer_mapping_complete` (all but `matched_by` together); `trg_deal_buyer_mapping_set_once` (`prevent_field_mutation_when_set`); `ix_deal_buyer_mapped_company`, `ix_deal_buyer_mapping_run`. **Data**: any `deal_buyer_company_map` rows are copied onto their buyers, then the map is dropped (only the `migrate_deal_buyers` command ever read it). Downgrade recreates the map, append-only trigger included, from the columns; lossless (one-to-one) | `onboarding_0055_config_freeze` |
| 0057 | Schema audit | `onboarding_0057_people`: directors and beneficial owners are people on `exporter_contact` — roles `is_contact` (default true), `is_director`, `is_ubo`; optional `date_of_birth`, `nationality`, `residence_country`, `din`, `ownership_pct`, `control_type`, `identification_type` / `identification_encrypted` / `identification_last4`, `source` / `source_ref`; 8 CHECKs (a role; primary is a contact; role-only fields; shapes; the identification triple); `uq_exporter_contact_id_customer`; `trg_exporter_contact_no_delete` with the new `onboarding.prevent_delete()`; `fk_sanctions_run_subject_person` (`(subject_reference, company_id)`, added `NOT VALID`, validated when no run breaks it, else the count and query are printed). **Data**: `ubo_record` owners whose request names a company are copied with their ids (`source = 'LEGACY_UBO_RECORD'`), one `person_added` history row each; the old system's tables are only read. Refuses if a linked owner carries a date of birth or identification number (possibly encrypted by the old system). Downgrade refuses while a director or owner exists that was not copied; otherwise removes the copies (history rows stay) and the structure | `onboarding_0056_buyer_map_cols` |
| 0058 | Schema audit | `onboarding_0058_buyer_freeze`: `deal_buyer` is frozen — `trg_deal_buyer_frozen` with the new `onboarding.prevent_deal_buyer_change()` refuses an `INSERT` and any `UPDATE` of the row's own columns; the buyer migration's mapping columns and `updated_at` stay writable. No data. Downgrade drops the trigger and the function | `onboarding_0057_people` |
| 0059 | Schema audit | `onboarding_0059_deal_reference`: `uq_deal_company_reference` — `UNIQUE (company_id, reference)` on `deal`. No data: **refuses** while any seller has two deals with one reference, and lists them. Downgrade drops it | `onboarding_0058_buyer_freeze` |
| 0060 | Schema audit | `onboarding_0060_drop_retired`: drops what the release before retired — `qualification_reason_code`, `bank_activity_finding`, `exporter_profile.relationship_manager`, `exporter_gstin.address`, `verification_result.reviewed_by`, `review_status` and `evidence_reference` with `trg_verification_result_field_immutability`; `prevent_reviewed_verification_outcome_change()` now reads the review chain alone. **Refuses**, changing nothing, while a GST branch has text and no address, RM text still names exactly one active RM account, a legacy verdict has no review in the chain, `evidence_reference` is set or `bank_activity_finding` has a row; prints how many unmatched RM names it discards. Downgrade recreates both tables (reason codes re-seeded), re-adds the columns **empty** and restores the trigger and the old function | `onboarding_0059_deal_reference` |

**Next free onboarding number: 0061.** Revision ids follow `onboarding_00NN_<lane>_<topic>`,
32 characters at most (§2 below).

`auth_0003` and `auth_0004` belong to the platform's user-management work, not to the
CRM (`auth_0005` only renames a row they seeded); they sit in this chain because
there is only one chain (§2), so a CRM migration written after them parents on them
like on any other.

### 0014 also adds the history foreign key

`exporter_lifecycle_history.customer_id` has no foreign key, and 0013
deliberately does not add one. 0014 recreates the CRM's own tables
and already owns the links for contacts, activities and screening items; the
history link goes in with them.

Putting it in 0013 instead would have forced 0014 to drop the constraint before
recreating `exporter_profile` and re-add it afterwards, for no gain — both land
in the same week. There are 1,498 history rows and zero orphans today, so the
constraint applies cleanly whenever 0014 runs.

---

## 2. Rules

**Name a migration `onboarding_00NN_<lane>_<topic>`.** `onboarding` is the module
whose directory holds it, `NN` the next free number from §1, `<lane>` the area of work
(`dev1`, `deal`, `domestic`, `verif`), `<topic>` what it does. The lane matters when
several people are migrating at once: it is what tells a reviewer whose change this is
without opening the file. Other modules use their own prefix — `auth_0004_rbac`.

Keep `<lane>_<topic>` short, because of the next rule. The limit is easy to breach:
`onboarding_0023_domestic_criteria` — the name first planned — is **33
characters** and failed on the database with `value too long for type character
varying(32)` after the migration body had already run. It shipped as
`onboarding_0031_domestic_first` (30).

**One chain, one head.** `alembic heads` must print exactly one revision. If it
prints two, someone branched: fix it by re-parenting, not by adding a merge
revision. The repository already carries three historical merge points from
before this register; do not add a fourth.

**Revision IDs are 32 characters or fewer.** Alembic's `version_num` column is
`varchar(32)`. A longer id fails at upgrade time, on the database, after the DDL
has started. `onboarding_0013_shared_history` is 30. The name first chosen for it,
`onboarding_0013_history_dimension`, is 33 and would have failed on the
database partway through the DDL — which is why the rule is written down.

**Never `ALTER TYPE ... ADD VALUE` inside an autocommit block.** It has broken
this repository before: the enum value commits, the rest of the migration does
not, and the database is left in a state no revision describes. `alembic_version`
still says the old revision, so a re-run tries to add a value that already
exists. Add the value in an ordinary transactional migration, as
`onboarding_0012_risk_critical` does.

**If the merge order changes, re-parent.** The later migration updates its own
`down_revision` (a one-line change) and whoever does it tells Dev 1 to update the
table above. Numbers are labels, not order; `down_revision` is the order. **If the
number itself has meanwhile been taken by a migration that merged first, take the
next free one as well** — two files carrying one number make §1 ambiguous. That is
what happened on 2 October 2026: Dev 2's 0025–0027 became 0028–0030 and Dev 3's
0023 became 0031.

The same rule, from the other direction: **before you merge, re-point
`down_revision` to whatever head is there now and re-run `alembic heads`.** A branch
that sat for a week was written against a head that has since moved. Reserve numbers
from §1 in the order the work is expected to merge, and accept that the expectation
will sometimes be wrong.

**Take a `pg_dump` before any migration that changes data**, not just schema. A data
migration that inserts rows into an append-only table cannot be undone by a plain
`DELETE` — the trigger refuses it — so its downgrade has to lift the trigger
deliberately, and a dump is what makes that safe to attempt. Each data migration says
in its docstring how it rolls back and what it changes about existing rows.

**Grow a column in three steps when a table is in use: expand, backfill, contract.**
Add the new column nullable, fill it, and only then make it `NOT NULL` or drop the old
one — in separate migrations. One migration that adds a `NOT NULL` column to a
populated table fails on the row it cannot fill.

**Register a new module migration directory in `alembic.ini`.** `version_locations`
is explicit, must stay on one line (Alembic splits it on commas and spaces, so a
multi-line list silently resolves to zero locations), and is checked by
`tests/contract/test_migration_discovery.py`, which derives the expected list
from the filesystem. A directory that exists but is unlisted is silently ignored
by `alembic upgrade head` — schema drift behind a green build.

**Every new constraint gets a direct-SQL violation test.** Established
throughout this project: the test bypasses the ORM with `psycopg2` and attempts
the violation, so it proves the *database* refuses it and not just the
application. This is how the append-only triggers are covered.

**0014 may drop and recreate the CRM's own tables** — the prototype starts from
sample data, so there is no data to migrate (decision 1). It must not touch the
legacy onboarding tables (`onboarding_request`, `onboarding_event`,
`onboarding_case`, `case_state_transition`) or any other module's tables.

**Downgrades are written, and lossy ones say so.** `onboarding_0011`'s downgrade
deletes superseded checklist decisions to restore a unique constraint and says
"Downgrade only if you mean it". Follow that: write the downgrade, and if it
destroys data, say which.

---

## 3. What must not be removed

The generalised history table is an **addition**. These stay:

- `public.prevent_mutation()` and every trigger that executes it (21 statements
  plus a loop in `customers_0002`).
- `onboarding.prevent_field_mutation_when_set()` and its column-level triggers.
- `AppendOnlyModel` / `AppendOnlyRepository`.
- `onboarding_event` — the legacy request path writes it, and its
  `onboarding_request_id` is `NOT NULL` with an FK, which is why lifecycle
  history needed its own table in the first place.
- `screening_review_item` — the checklist's own superseding log. Dev 4 needs it.
- `case_state_transition` and the 12-state legacy case machine — out of scope
  for the prototype (assumption A6), not deleted.
- Existing `exporter_lifecycle_history` rows. 0013 backfills them; it does not
  truncate them.

---

## 4. Before and after every migration

```bash
cd backend
alembic heads                 # exactly one
alembic upgrade head
alembic downgrade -1          # and back
alembic upgrade head          # the round trip must be clean
python -m pytest -q --no-cov -p no:cacheprovider
```

Compare the suite against the current baseline in `docs/development.md` — the
known failures are payments/FX/compliance-screening tests hitting routes this
checkout does not mount. Any other failure is new and blocks the merge.

`backend/tests/contract/test_orm_matches_the_onboarding_schema.py` also fails when a
migration adds an index or constraint in the `onboarding` schema without the model
declaring it (or the other way round), so `alembic revision --autogenerate` never
proposes dropping one.

---

## 5. History before this register

71 revisions existed before 0013, with one head (`onboarding_0012_risk_critical`).
Two duplicate numbers exist in other modules — `compliance_0002` and
`rails_0003` each appear twice. They are historical, they resolve correctly, and
they are **left alone**.
