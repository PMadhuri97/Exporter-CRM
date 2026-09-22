"""ledger module baseline — schema `ledger`

Squash of the 15 ledger migrations c1a2b3c4d5e2 .. c1a2b3c4d5f6, plus
c1a2b3c4d5f7 (negative balance prevention), plus the ledger portion of
41735b67723b, expressed as the final desired schema only.

Everything is created inside the dedicated `ledger` schema:

  ledger.ledger_account      — the account record, scoped to exactly one asset.
  ledger.ledger_transaction  — the atomicity unit; a balanced set of entries.
  ledger.ledger_entry        — the individual debit/credit line. Append-only.
  ledger.account_balance     — materialised current balance, for read performance.

Invariants enforced at the database level:
  Rule 1  amount, balance_before, balance_after are BIGINT integer minor units.
  Rule 2  ledger_entry is append-only — prevent_mutation() blocks UPDATE/DELETE.
  Rule 3  every (transaction, asset) nets to zero — deferred constraint trigger.
  Rule 4  a customer account's balance may never go negative — post_entry_balance().

ERRCODE conventions carried forward unchanged:
  ANER1 — ledger transaction not balanced / not postable
  ANER2 — no account_balance row for a ledger account
  ANER3 — ledger_transaction core field mutated
  ANER4 — ledger_account core field mutated
  ANER5 — illegal DELETE on financial record
  ANER6 — customer account balance would go negative

Constraint names are preserved exactly as they exist in the pre-squash database,
including the plural residuals left behind by `ALTER TABLE ... RENAME TO` in
c1a2b3c4d5e5 (PostgreSQL does not rename a table's constraints or their backing
indexes). `ledger_accounts_pkey`, `ledger_entries_transaction_id_fkey`,
`account_balances_account_id_fkey`,
`ledger_transactions_compensates_transaction_id_fkey` and
`ck_ledger_entries_amount_positive` are therefore spelled out explicitly rather
than left to PostgreSQL's auto-naming, which would produce singular forms and
silently change the schema.

Column order reproduces the physical order in the pre-squash database. The only
table where that is not the natural reading order is `ledger_entry`: `entry_seq`
sits last because c1a2b3c4d5f2 appended it to an existing table.

EXTERNAL DEPENDENCY: the `ledger_entry_immutable` trigger executes
`public.prevent_mutation()`, which is created by the shared bootstrap migration
a0b1c2d3e4f5 and is not owned by this module. It is referenced schema-qualified
so the reference cannot be broken by a search_path change.

Revision ID: ledger_0001_baseline
Revises: reconciliation_0001_baseline
Create Date: 2026-08-05
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "ledger_0001_baseline"
down_revision: str | None = "reconciliation_0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SCHEMA = "ledger"

# Asset codes are registry codes (USD, INR, USDC, ...). 16 leaves headroom for
# longer token symbols without another widening migration.
ASSET_CODE_LEN = 16


# ── Enums ─────────────────────────────────────────────────────────────────────
# Values are the lowercase spec values, not the Python member names: the models
# pass values_callable, so the stored labels must match these exactly.

account_type_enum = postgresql.ENUM(
    "customer", "treasury", "fee", "reserve", "clearing",
    name="ledger_account_type_enum",
    schema=SCHEMA,
    create_type=False,
)
entity_type_enum = postgresql.ENUM(
    "customer", "platform", "fee_pool", "clearing_pool",
    name="ledger_entity_type_enum",
    schema=SCHEMA,
    create_type=False,
)
account_status_enum = postgresql.ENUM(
    "active", "suspended", "closed",
    name="ledger_account_status_enum",
    schema=SCHEMA,
    create_type=False,
)
transaction_type_enum = postgresql.ENUM(
    "settlement_debit", "settlement_credit", "fee_debit", "compensation",
    "prefund_movement", "fx_conversion",
    name="ledger_transaction_type_enum",
    schema=SCHEMA,
    create_type=False,
)
transaction_status_enum = postgresql.ENUM(
    "pending", "posted", "failed",
    name="ledger_transaction_status_enum",
    schema=SCHEMA,
    create_type=False,
)
direction_enum = postgresql.ENUM(
    "debit", "credit",
    name="ledger_direction_enum",
    schema=SCHEMA,
    create_type=False,
)

_ENUMS = (
    account_type_enum,
    entity_type_enum,
    account_status_enum,
    transaction_type_enum,
    transaction_status_enum,
    direction_enum,
)


def upgrade() -> None:
    bind = op.get_bind()

    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    # Created explicitly up front rather than inline: create_type=False on the
    # column definitions keeps create_table from emitting CREATE TYPE a second
    # time for any enum that gains a second column later.
    for pg_enum in _ENUMS:
        pg_enum.create(bind, checkfirst=False)

    # ── ledger_account ────────────────────────────────────────────────────────
    op.create_table(
        "ledger_account",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("account_type", account_type_enum, nullable=False),
        sa.Column("asset_code", sa.String(length=ASSET_CODE_LEN), nullable=False),
        # Denormalised from CURRENCY_REGISTRY and immutable once set. Changing
        # precision on a live account would silently corrupt every stored
        # minor-unit balance, which is why the column guard below covers it.
        sa.Column("precision", sa.Integer(), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("entity_type", entity_type_enum, nullable=False),
        sa.Column("status", account_status_enum, nullable=False, server_default="active"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.PrimaryKeyConstraint("id", name="ledger_accounts_pkey"),
        # Target of the composite FK on ledger_entry: guarantees an entry's
        # asset_code always matches its account's asset_code.
        sa.UniqueConstraint("id", "asset_code", name="uq_ledger_account_id_asset"),
        # Spec: precision accepts only 2 (fiat), 6 (USDC), or 18 (ERC-20 tokens).
        sa.CheckConstraint(
            "precision IN (2, 6, 18)",
            name="ck_ledger_account_precision_allowed_values",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_ledger_account_entity",
        "ledger_account",
        ["entity_id", "asset_code"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_ledger_account_type_asset",
        "ledger_account",
        ["account_type", "asset_code"],
        schema=SCHEMA,
    )
    op.create_index(
        "uq_ledger_account_one_active",
        "ledger_account",
        ["entity_id", "account_type", "asset_code"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
        schema=SCHEMA,
    )

    # ── ledger_transaction ────────────────────────────────────────────────────
    op.create_table(
        "ledger_transaction",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("transaction_type", transaction_type_enum, nullable=False),
        sa.Column("status", transaction_status_enum, nullable=False, server_default="pending"),
        sa.Column("correlation_id", sa.String(length=255), nullable=False),
        # No FK: settlement.settlement is owned by another module and this column
        # has never carried a constraint.
        sa.Column("settlement_id", sa.UUID(), nullable=True),
        sa.Column("compensates_transaction_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.ForeignKeyConstraint(
            ["compensates_transaction_id"],
            [f"{SCHEMA}.ledger_transaction.id"],
            name="ledger_transactions_compensates_transaction_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="ledger_transactions_pkey"),
        sa.CheckConstraint(
            "(transaction_type = 'compensation') = (compensates_transaction_id IS NOT NULL)",
            name="ck_compensation_link",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_ledger_transaction_settlement",
        "ledger_transaction",
        ["settlement_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_ledger_transaction_correlation",
        "ledger_transaction",
        ["correlation_id"],
        schema=SCHEMA,
    )
    # Idempotency uniqueness is an index, not a table constraint — c1a2b3c4d5f2
    # dropped the original uq_ledger_transactions_idempotency constraint in favour
    # of this index and it has stayed an index ever since.
    op.create_index(
        "uq_ledger_txn_idem",
        "ledger_transaction",
        ["idempotency_key"],
        unique=True,
        schema=SCHEMA,
    )
    # A transaction may be compensated at most once.
    op.create_index(
        "uq_txn_single_compensation",
        "ledger_transaction",
        ["compensates_transaction_id"],
        unique=True,
        postgresql_where=sa.text("compensates_transaction_id IS NOT NULL"),
        schema=SCHEMA,
    )

    # ── ledger_entry ──────────────────────────────────────────────────────────
    op.create_table(
        "ledger_entry",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("transaction_id", sa.UUID(), nullable=False),
        sa.Column("account_id", sa.UUID(), nullable=False),
        sa.Column("direction", direction_enum, nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("asset_code", sa.String(length=ASSET_CODE_LEN), nullable=False),
        # Populated by post_entry_balance() BEFORE INSERT. NOT NULL is safe:
        # constraint checks run after BEFORE triggers have modified NEW.
        sa.Column("balance_before", sa.BigInteger(), nullable=False),
        sa.Column("balance_after", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        # Last, not second: c1a2b3c4d5f2 appended this column to an existing
        # table, so it holds the final ordinal position in the live database.
        sa.Column(
            "entry_seq",
            sa.BigInteger(),
            sa.Identity(always=True),
            nullable=False,
            comment=(
                "Monotonic post-order sequence. The ONLY valid sort key for replay, "
                "history, and integrity checks. Gaps are expected and permitted. "
                "created_at is NOT a valid sort key - entries within a transaction "
                "share an identical timestamp."
            ),
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            [f"{SCHEMA}.ledger_transaction.id"],
            name="ledger_entries_transaction_id_fkey",
            ondelete="RESTRICT",
        ),
        # An entry's asset must match its account's asset — structural, not a
        # service-layer check.
        sa.ForeignKeyConstraint(
            ["account_id", "asset_code"],
            [f"{SCHEMA}.ledger_account.id", f"{SCHEMA}.ledger_account.asset_code"],
            name="fk_ledger_entry_account_asset",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="ledger_entries_pkey"),
        # Rule 1: amounts are positive integers; direction carries the sign.
        sa.CheckConstraint("amount > 0", name="ck_ledger_entries_amount_positive"),
        schema=SCHEMA,
    )
    # Required, not cosmetic: the balance trigger re-aggregates this group once
    # per inserted row.
    op.create_index(
        "ix_ledger_entry_tx_asset",
        "ledger_entry",
        ["transaction_id", "asset_code"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_ledger_entry_account",
        "ledger_entry",
        ["account_id", "created_at"],
        schema=SCHEMA,
    )
    op.create_index(
        "uq_ledger_entry_seq",
        "ledger_entry",
        ["entry_seq"],
        unique=True,
        schema=SCHEMA,
    )
    op.create_index(
        "ix_ledger_entry_account_seq",
        "ledger_entry",
        ["account_id", "entry_seq"],
        schema=SCHEMA,
    )

    # ── account_balance ───────────────────────────────────────────────────────
    # Created after ledger_entry so fk_account_balance_last_entry can be declared
    # inline rather than added afterwards.
    op.create_table(
        "account_balance",
        sa.Column("account_id", sa.UUID(), nullable=False),
        sa.Column("balance", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("asset_code", sa.String(length=ASSET_CODE_LEN), nullable=False),
        # The entry that last moved this balance; set by post_entry_balance().
        # NULL only for a freshly created account not yet posted to.
        sa.Column("last_entry_id", sa.UUID(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            [f"{SCHEMA}.ledger_account.id"],
            name="account_balances_account_id_fkey",
            ondelete="RESTRICT",
        ),
        # DEFERRABLE INITIALLY DEFERRED is required, not optional:
        # post_entry_balance() sets account_balance.last_entry_id = NEW.id inside
        # the BEFORE INSERT trigger, i.e. before the entry row exists in
        # ledger_entry. A non-deferred FK would fail there. Deferred, the
        # reference is checked at COMMIT, by which point the entry is inserted.
        sa.ForeignKeyConstraint(
            ["last_entry_id"],
            [f"{SCHEMA}.ledger_entry.id"],
            name="fk_account_balance_last_entry",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.PrimaryKeyConstraint("account_id", name="account_balances_pkey"),
        schema=SCHEMA,
    )

    # ── Functions ─────────────────────────────────────────────────────────────
    # Every table reference is schema-qualified: these run with whatever
    # search_path the caller has, and ledger is not on it by default.

    # Auto-create the balance row with the account.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {SCHEMA}.create_account_balance()
        RETURNS trigger AS $$
        BEGIN
            INSERT INTO {SCHEMA}.account_balance (account_id, balance, asset_code, updated_at)
            VALUES (NEW.id, 0, NEW.asset_code, now())
            ON CONFLICT (account_id) DO NOTHING;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # Balance chain + materialised balance.
    # Sign convention (D1): balances are debit-positive. A debit adds +amount, a
    # credit adds -amount, so the entries of a balanced transaction leave the sum
    # of all touched balances unchanged.
    #
    # The SELECT ... FOR UPDATE below serialises concurrent postings to the same
    # account, so the chain has no gaps and no two entries share a
    # balance_before. Callers must insert entries in a deterministic account
    # order or two concurrent multi-account transactions can deadlock there.
    #
    # That note is deliberately a Python comment rather than a PL/pgSQL one:
    # c1a2b3c4d5e8 rewrote this body without the inline comment, so the stored
    # prosrc in a pre-squash database does not contain it. Keeping it out of the
    # SQL string is what makes the squashed function byte-identical to the one
    # the old chain produced.
    # Rule 4: a customer account may never be debited below zero. acc_type is
    # looked up rather than carried on the entry so the check stays correct even
    # if an account's type changes; ANER6 is distinct from ANER1/ANER2 so the
    # posting service can tell "insufficient funds" apart from "unknown account".
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {SCHEMA}.post_entry_balance()
        RETURNS trigger AS $$
        DECLARE
            prev  BIGINT;
            delta BIGINT;
            acc_type TEXT;
        BEGIN
            delta := CASE WHEN NEW.direction = 'debit'
                          THEN NEW.amount ELSE -NEW.amount END;

            SELECT balance INTO prev
              FROM {SCHEMA}.account_balance
             WHERE account_id = NEW.account_id
               FOR UPDATE;

            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'No account_balance row for ledger account %; it must be created with the account',
                    NEW.account_id
                    USING ERRCODE = 'ANER2';
            END IF;

            SELECT account_type::TEXT INTO acc_type
              FROM {SCHEMA}.ledger_account
             WHERE id = NEW.account_id;

            NEW.balance_before := prev;
            NEW.balance_after  := prev + delta;

            IF acc_type = 'customer' AND NEW.direction = 'debit' AND NEW.balance_after > 0 THEN
                RAISE EXCEPTION
                    'Customer account % balance cannot go below zero: requested debit of % would result in balance %',
                    NEW.account_id, NEW.amount, NEW.balance_after
                    USING ERRCODE = 'ANER6';
            END IF;

            UPDATE {SCHEMA}.account_balance
               SET balance       = NEW.balance_after,
                   last_entry_id = NEW.id,
                   updated_at    = now()
             WHERE account_id = NEW.account_id;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # Rule 3: balance before post.
    # Grouped by (transaction_id, asset_code), NOT transaction_id alone: an
    # fx_conversion carries two assets under one transaction and each must net to
    # zero on its own. Amounts in different assets are never summed together.
    #
    # ERRCODE is a custom 'ANER1' rather than check_violation (23514) on purpose:
    # 23514 maps to SQLAlchemy IntegrityError, which this service already uses to
    # mean "duplicate idempotency key". An out-of-balance ledger must not surface
    # to the caller as a duplicate-key conflict.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {SCHEMA}.assert_ledger_transaction_balanced()
        RETURNS trigger AS $$
        DECLARE net BIGINT;
        BEGIN
            SELECT COALESCE(SUM(CASE WHEN direction = 'debit'
                                     THEN amount ELSE -amount END), 0)
              INTO net
              FROM {SCHEMA}.ledger_entry
             WHERE transaction_id = NEW.transaction_id
               AND asset_code     = NEW.asset_code;

            IF net <> 0 THEN
                RAISE EXCEPTION
                    'Ledger transaction % does not net to zero for asset %: net = %',
                    NEW.transaction_id, NEW.asset_code, net
                    USING ERRCODE = 'ANER1',
                          HINT = 'Debits must equal credits per asset. Corrections are compensating entries, never edits.';
            END IF;

            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # A transaction may not be marked posted unless it is genuinely balanced.
    # The deferred trigger above only fires on INSERT, so a transaction with zero
    # entries would otherwise sail through to 'posted'.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {SCHEMA}.assert_ledger_transaction_postable()
        RETURNS trigger AS $$
        DECLARE
            entry_count INTEGER;
            unbalanced  TEXT;
        BEGIN
            SELECT COUNT(*) INTO entry_count
              FROM {SCHEMA}.ledger_entry WHERE transaction_id = NEW.id;

            IF entry_count < 2 THEN
                RAISE EXCEPTION
                    'Ledger transaction % cannot post with % entr(y/ies): at least two are required',
                    NEW.id, entry_count
                    USING ERRCODE = 'ANER1';
            END IF;

            SELECT string_agg(asset_code, ', ') INTO unbalanced
              FROM (
                SELECT asset_code
                  FROM {SCHEMA}.ledger_entry
                 WHERE transaction_id = NEW.id
                 GROUP BY asset_code
                HAVING SUM(CASE WHEN direction = 'debit'
                                THEN amount ELSE -amount END) <> 0
              ) AS bad;

            IF unbalanced IS NOT NULL THEN
                RAISE EXCEPTION
                    'Ledger transaction % cannot post: asset(s) % do not net to zero',
                    NEW.id, unbalanced
                    USING ERRCODE = 'ANER1';
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # ledger_transaction: only status and posted_at are mutable.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {SCHEMA}.guard_ledger_transaction_core()
        RETURNS trigger AS $$
        BEGIN
            IF NEW.id                          IS DISTINCT FROM OLD.id                          OR
               NEW.idempotency_key             IS DISTINCT FROM OLD.idempotency_key             OR
               NEW.transaction_type            IS DISTINCT FROM OLD.transaction_type            OR
               NEW.correlation_id              IS DISTINCT FROM OLD.correlation_id              OR
               NEW.settlement_id               IS DISTINCT FROM OLD.settlement_id               OR
               NEW.compensates_transaction_id  IS DISTINCT FROM OLD.compensates_transaction_id  OR
               NEW.created_at                  IS DISTINCT FROM OLD.created_at                  OR
               NEW.created_by                  IS DISTINCT FROM OLD.created_by
            THEN
                RAISE EXCEPTION
                    'ledger_transaction %: immutable core fields may not be updated '
                    '(only status and posted_at are mutable)',
                    OLD.id
                    USING ERRCODE = 'ANER3';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # ledger_account: only status and metadata are mutable.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {SCHEMA}.guard_ledger_account_core()
        RETURNS trigger AS $$
        BEGIN
            IF NEW.id           IS DISTINCT FROM OLD.id           OR
               NEW.account_type IS DISTINCT FROM OLD.account_type OR
               NEW.asset_code   IS DISTINCT FROM OLD.asset_code   OR
               NEW.precision    IS DISTINCT FROM OLD.precision     OR
               NEW.entity_id    IS DISTINCT FROM OLD.entity_id    OR
               NEW.entity_type  IS DISTINCT FROM OLD.entity_type  OR
               NEW.created_at   IS DISTINCT FROM OLD.created_at
            THEN
                RAISE EXCEPTION
                    'ledger_account %: immutable core fields may not be updated '
                    '(only status and metadata are mutable)',
                    OLD.id
                    USING ERRCODE = 'ANER4';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # DELETE is blocked on both financial records: a closed account still carries
    # the history of all its entries and must outlive the account's active life.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {SCHEMA}.prevent_financial_record_delete()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                'Table % is a financial record: DELETE is permanently forbidden. '
                'Use status transitions or compensating entries instead.',
                TG_TABLE_NAME
                USING ERRCODE = 'ANER5';
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # A compensation may not itself be compensated.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {SCHEMA}.prevent_compensation_chain()
        RETURNS trigger AS $$
        DECLARE
            target_type TEXT;
        BEGIN
            IF NEW.compensates_transaction_id IS NOT NULL THEN
                SELECT transaction_type INTO target_type
                  FROM {SCHEMA}.ledger_transaction
                 WHERE id = NEW.compensates_transaction_id;

                IF target_type = 'compensation' THEN
                    RAISE EXCEPTION
                        'Cannot compensate a compensation transaction (id=%). '
                        'Use a corrective adjustment instead.',
                        NEW.compensates_transaction_id
                        USING ERRCODE = 'check_violation';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # Strict-mirror verification (final definition, from c1a2b3c4d5f6).
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {SCHEMA}.is_strict_mirror(p_compensation_txn UUID)
        RETURNS BOOLEAN
        LANGUAGE sql
        STABLE
        AS $$
            WITH target AS (
                SELECT compensates_transaction_id AS tid
                FROM {SCHEMA}.ledger_transaction
                WHERE id = p_compensation_txn
                  AND compensates_transaction_id IS NOT NULL
            ),
            expected AS (
                -- What an exact reversal of the original must look like.
                SELECT
                    e.account_id,
                    e.asset_code::text,
                    (CASE e.direction
                         WHEN 'debit' THEN 'credit'
                         ELSE 'debit'
                     END)::text AS direction,
                    e.amount
                FROM {SCHEMA}.ledger_entry e
                JOIN target ON e.transaction_id = target.tid
            ),
            actual AS (
                SELECT account_id, asset_code::text, direction::text, amount
                FROM {SCHEMA}.ledger_entry
                WHERE transaction_id = p_compensation_txn
            )
            SELECT
                EXISTS (SELECT 1 FROM expected)
            AND NOT EXISTS (SELECT * FROM expected EXCEPT ALL SELECT * FROM actual)
            AND NOT EXISTS (SELECT * FROM actual EXCEPT ALL SELECT * FROM expected);
        $$;
        """
    )
    op.execute(
        f"""
        COMMENT ON FUNCTION {SCHEMA}.is_strict_mirror(UUID) IS
            'True when the given transaction links to a target and its entries are an '
            'exact, complete reversal of that target. False for an unknown id, a '
            'transaction that compensates nothing, and an empty reversal. EXCEPT ALL '
            'preserves multiplicity, so a transaction touching the same account twice '
            'is compared correctly.';
        """
    )

    # Diagnostic companion to is_strict_mirror(): returns the expected-vs-actual
    # delta. Called by the posting service when a mirror check fails.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {SCHEMA}.mirror_diff(p_compensation_txn UUID)
        RETURNS TABLE (
            side        TEXT,
            account_id  UUID,
            asset_code  TEXT,
            direction   TEXT,
            amount      BIGINT
        )
        LANGUAGE sql
        STABLE
        AS $$
            WITH target AS (
                SELECT compensates_transaction_id AS tid
                FROM {SCHEMA}.ledger_transaction WHERE id = p_compensation_txn
            ),
            expected AS (
                SELECT e.account_id, e.asset_code::text,
                       (CASE e.direction WHEN 'debit' THEN 'credit' ELSE 'debit' END)::text,
                       e.amount
                FROM {SCHEMA}.ledger_entry e JOIN target ON e.transaction_id = target.tid
            ),
            actual AS (
                SELECT account_id, asset_code::text, direction::text, amount
                FROM {SCHEMA}.ledger_entry WHERE transaction_id = p_compensation_txn
            )
            SELECT 'missing_from_compensation', * FROM (
                SELECT * FROM expected EXCEPT ALL SELECT * FROM actual
            ) a
            UNION ALL
            SELECT 'unexpected_in_compensation', * FROM (
                SELECT * FROM actual EXCEPT ALL SELECT * FROM expected
            ) b;
        $$;
        """
    )

    # ── Triggers ──────────────────────────────────────────────────────────────

    # ledger_account
    op.execute(
        f"""
        CREATE TRIGGER ledger_account_create_balance
        AFTER INSERT ON {SCHEMA}.ledger_account
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.create_account_balance();
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER ledger_account_core_immutable
        BEFORE UPDATE ON {SCHEMA}.ledger_account
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.guard_ledger_account_core();
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER ledger_account_no_delete
        BEFORE DELETE ON {SCHEMA}.ledger_account
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.prevent_financial_record_delete();
        """
    )

    # ledger_transaction
    op.execute(
        f"""
        CREATE TRIGGER ledger_transaction_no_compensation_chain
        BEFORE INSERT ON {SCHEMA}.ledger_transaction
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.prevent_compensation_chain();
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER ledger_transaction_core_immutable
        BEFORE UPDATE ON {SCHEMA}.ledger_transaction
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.guard_ledger_transaction_core();
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER ledger_transaction_postable
        BEFORE UPDATE ON {SCHEMA}.ledger_transaction
        FOR EACH ROW
        WHEN (NEW.status = 'posted' AND OLD.status IS DISTINCT FROM 'posted')
        EXECUTE FUNCTION {SCHEMA}.assert_ledger_transaction_postable();
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER ledger_transaction_no_delete
        BEFORE DELETE ON {SCHEMA}.ledger_transaction
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.prevent_financial_record_delete();
        """
    )

    # ledger_entry
    # Rule 2: append-only. prevent_mutation() is owned by the shared root
    # migration and lives in public — referenced schema-qualified on purpose.
    op.execute(
        f"""
        CREATE TRIGGER ledger_entry_immutable
        BEFORE UPDATE OR DELETE ON {SCHEMA}.ledger_entry
        FOR EACH ROW EXECUTE FUNCTION public.prevent_mutation();
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER ledger_entry_post_balance
        BEFORE INSERT ON {SCHEMA}.ledger_entry
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.post_entry_balance();
        """
    )
    op.execute(
        f"""
        CREATE CONSTRAINT TRIGGER ledger_transaction_balanced
        AFTER INSERT ON {SCHEMA}.ledger_entry
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.assert_ledger_transaction_balanced();
        """
    )


def downgrade() -> None:
    # CASCADE reaches the tables, indexes, constraints, triggers, functions, enum
    # types and the entry_seq identity sequence in one statement, plus any foreign
    # key another schema holds into ledger.
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
