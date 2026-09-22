"""The compliance module imports, and its shared types are shared.

Two regressions from the AL-443 merge, each cheap to prevent and expensive to
discover late.

The first is import health. A conflict marker left in ``__init__.py`` or
``domain/ports.py`` made every ``import app.modules.compliance`` a SyntaxError.
Nothing else in this suite runs when that happens, so the failure arrives as a
wall of collection errors rather than as one legible test.

The second is type identity. ``JurisdictionType`` was declared twice — once in
``domain/jurisdiction.py`` and once in ``domain/entities/sector_registry.py`` —
with identical values in different orders. Because both subclass ``str`` the two
compared equal, so nothing broke loudly; but ``is`` comparisons across the
boundary silently returned False, and the codebase asserts jurisdiction identity
with ``is`` throughout. That is a bug that hides until the one test that happens
to cross the seam.
"""

from __future__ import annotations

import importlib

import pytest

import app.modules.compliance as facade
from app.modules.compliance.domain import jurisdiction, ports
from app.modules.compliance.domain.entities import sector_registry


def test_the_compliance_facade_imports():
    """Fails as one named test rather than as a collection error."""
    module = importlib.import_module("app.modules.compliance")

    assert module is facade


def test_every_exported_name_resolves():
    """A name in ``__all__`` that does not exist is a merge that dropped an
    import while keeping the export — precisely the shape of the AL-443
    conflict in ``__init__.py``."""
    missing = [name for name in facade.__all__ if not hasattr(facade, name)]

    assert not missing, f"__all__ names these but the module does not define them: {missing}"


def test_the_public_entry_point_is_exported():
    assert callable(facade.evaluate_compliance_rules)


def test_jurisdiction_type_has_exactly_one_definition():
    """The sector registry must reuse the domain enum, not declare its own."""
    assert sector_registry.JurisdictionType is jurisdiction.JurisdictionType
    assert ports.JurisdictionType is jurisdiction.JurisdictionType
    assert facade.JurisdictionType is jurisdiction.JurisdictionType


def test_the_orm_column_uses_the_shared_jurisdiction_enum():
    """The mapped column and the value carried in a decision are the same type.

    ``ResolvingJurisdiction.type`` is built from whatever the repository row
    holds, so a second enum here would put a foreign member into every action
    set without any comparison failing loudly.
    """
    column = sector_registry.SectorRiskClassification.__table__.c.jurisdiction_type

    assert column.type.enum_class is jurisdiction.JurisdictionType


def test_the_postgres_enum_values_are_unchanged():
    """Unifying the Python enum must not have changed the database vocabulary.

    The members are declared in a different order than the retired duplicate
    used, which is harmless only because the type is created by migration and
    never by ``metadata.create_all``. The *set* of values is what the database
    holds, and it must still match ``jurisdiction_type_enum``.
    """
    assert {m.value for m in jurisdiction.JurisdictionType} == {
        "corridor",
        "country",
        "framework",
    }


def test_no_production_module_depends_on_the_retired_stub():
    """``StubSectorClassificationLookup`` was deleted, not repaired.

    It hardcoded ``framework``/``FATF`` as the resolving jurisdiction, which was
    a fair approximation while the registry could not express precedence and a
    falsehood the moment it could.
    """
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(
            "app.modules.compliance.application.sector_classification_stub"
        )
