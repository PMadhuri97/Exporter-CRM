"""Currency/asset_code columns must be wide enough for registry asset codes.

Reads column lengths from SQLAlchemy metadata (DB-free) and fails if any currency
column is too narrow to hold a registry code.
"""
import pytest

# Import model modules so their tables register on Base.metadata.
import app.modules.customers.domain.entities  # noqa: F401
import app.modules.fx.domain.entities.fx  # noqa: F401
import app.modules.ledger.domain.entities.ledger  # noqa: F401
import app.modules.payments.domain.entities.payments  # noqa: F401
import app.modules.settlement.domain.entities.settlement  # noqa: F401
from app.platform.database.models import Base
from app.shared.value_objects import CURRENCY_REGISTRY

_MIN_WIDTH = 8

# Every (table, column) that may hold a currency / registry asset code.
# Keys are schema-qualified: each module owns a PostgreSQL schema, and
# Base.metadata.tables is keyed "<schema>.<table>" for any table carrying one.
_CURRENCY_COLUMNS = [
    ("customers.beneficiary_bank_accounts", "currency"),
    ("customers.customer_entitlement", "limit_currency"),
    ("ledger.ledger_account", "asset_code"),
    ("ledger.ledger_entry", "asset_code"),
    ("ledger.account_balance", "asset_code"),
    ("settlement.settlement_legs", "currency"),
    ("payments.transactions", "source_currency"),
    ("payments.transactions", "destination_currency"),
    ("fx.fx_quotes", "from_currency"),
    ("fx.fx_quotes", "to_currency"),
]


@pytest.mark.parametrize("table, column", _CURRENCY_COLUMNS)
def test_currency_column_is_wide_enough(table, column):
    col = Base.metadata.tables[table].columns[column]
    assert col.type.length >= _MIN_WIDTH, (
        f"{table}.{column} is VARCHAR({col.type.length}); needs >= {_MIN_WIDTH}"
    )


def test_width_covers_every_registered_asset_code():
    longest = max(len(code) for code in CURRENCY_REGISTRY.codes())
    assert longest <= _MIN_WIDTH, (
        f"a registered asset code ({longest} chars) exceeds the column width {_MIN_WIDTH}"
    )
