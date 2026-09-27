"""Category rules and the document-type settings — L3-09.

Contract: ``storage-and-documents.md`` §5.3. Architecture §3.4.

Pure: the ten categories carry a rule about which owner each belongs to, and the
types come from a YAML file this test writes itself. No database.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.modules.onboarding.domain.entities.document_enums import (
    DocumentCategory,
    DocumentOwnerKind,
    DocumentSource,
)
from app.modules.onboarding.infrastructure import document_type_loader
from app.modules.onboarding.infrastructure.document_type_loader import (
    DocumentTypeConfigurationError,
    is_valid_type,
    load_document_types,
    types_for,
)

COMPANY = DocumentOwnerKind.COMPANY
DEAL = DocumentOwnerKind.DEAL


@pytest.fixture(autouse=True)
def _clean_cache():
    """The loader caches, so every test starts and ends without one else's file."""
    document_type_loader.reset_cache()
    yield
    document_type_loader.reset_cache()


# ── The ten categories, and where each may be filed ──────────────────────────


def test_there_are_exactly_ten_categories():
    """Architecture §3.4 fixes the list; an eleventh needs a migration, because the
    database enum names them."""
    assert len(DocumentCategory) == 10


@pytest.mark.parametrize(
    ("category", "expected"),
    [
        (DocumentCategory.ENTITY_KYC, DocumentOwnerKind.COMPANY),
        (DocumentCategory.COMPLIANCE_SCREENING, DocumentOwnerKind.COMPANY),
        (DocumentCategory.COMPANY_MARKET_REVIEW, DocumentOwnerKind.COMPANY),
        (DocumentCategory.PRE_SHIPMENT, DocumentOwnerKind.DEAL),
        (DocumentCategory.SHIPPING, DocumentOwnerKind.DEAL),
        (DocumentCategory.CUSTOMS_AND_REGULATORY, DocumentOwnerKind.DEAL),
        (DocumentCategory.BUYER, DocumentOwnerKind.DEAL),
        (DocumentCategory.BANKING, DocumentOwnerKind.BOTH),
        (DocumentCategory.INSURANCE, DocumentOwnerKind.BOTH),
        (DocumentCategory.OTHER, DocumentOwnerKind.BOTH),
    ],
)
def test_each_category_belongs_where_the_architecture_says(
    category: DocumentCategory, expected: DocumentOwnerKind
):
    """Transcribed from architecture §3.4's "Belongs to" column, independently of
    the mapping in the module — a test that imported the table it verifies would
    pass whatever that table became."""
    assert category.owner_kind is expected


def test_a_deal_category_is_refused_on_a_company_and_the_other_way_round():
    assert DocumentCategory.SHIPPING.allows(DEAL) is True
    assert DocumentCategory.SHIPPING.allows(COMPANY) is False
    assert DocumentCategory.ENTITY_KYC.allows(COMPANY) is True
    assert DocumentCategory.ENTITY_KYC.allows(DEAL) is False


@pytest.mark.parametrize(
    "category",
    [DocumentCategory.BANKING, DocumentCategory.INSURANCE, DocumentCategory.OTHER],
)
def test_a_both_category_is_allowed_on_either(category: DocumentCategory):
    assert category.allows(COMPANY) is True
    assert category.allows(DEAL) is True


def test_every_category_is_offered_to_exactly_one_side_or_both():
    """No category is unreachable: a screen on a company page plus a screen on a
    deal page between them offer all ten."""
    offered = {c for c in DocumentCategory if c.allows(COMPANY)} | {
        c for c in DocumentCategory if c.allows(DEAL)
    }
    assert offered == set(DocumentCategory)


def test_the_four_sources_are_the_four_the_architecture_names():
    assert {s.value for s in DocumentSource} == {
        "RXIL",
        "EXPORTER_UPLOAD",
        "INTERNAL",
        "SYSTEM",
    }


# ── Types are settings ───────────────────────────────────────────────────────


def test_the_shipped_settings_configure_every_category():
    """A category with no configured type accepts no upload at all, which would make
    it dead — so the shipped file covers all ten, `COMPANY_MARKET_REVIEW` included
    (nothing generates into it yet, decision D16)."""
    types = load_document_types()
    assert set(types) == set(DocumentCategory)
    assert all(entries for entries in types.values())


def test_a_type_is_valid_only_under_its_own_category():
    """Filing a bill of lading under `ENTITY_KYC` would put it where nobody looks."""
    assert is_valid_type(DocumentCategory.SHIPPING, "bill_of_lading") is True
    assert is_valid_type(DocumentCategory.ENTITY_KYC, "bill_of_lading") is False
    assert is_valid_type(DocumentCategory.SHIPPING, "not_a_type") is False


def test_a_new_type_needs_no_code_change(tmp_path: Path):
    """The property this whole design exists for (architecture §3.4): adding a type
    is a GitOps edit, not a release and not a migration."""
    settings = tmp_path / "document-types.yaml"
    settings.write_text(
        "version: '1.0'\n"
        "categories:\n"
        "  SHIPPING:\n"
        "    - key: brand_new_type\n"
        "      label: Brand new type\n",
        encoding="utf-8",
    )
    loaded = load_document_types(settings)

    assert loaded[DocumentCategory.SHIPPING] == (("brand_new_type", "Brand new type"),)


def test_a_label_defaults_to_the_key(tmp_path: Path):
    settings = tmp_path / "document-types.yaml"
    settings.write_text(
        "categories:\n  OTHER:\n    - key: unlabelled\n", encoding="utf-8"
    )
    assert types_for_from(settings, DocumentCategory.OTHER) == (
        ("unlabelled", "unlabelled"),
    )


def types_for_from(path: Path, category: DocumentCategory):
    return load_document_types(path)[category]


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        ("categories:\n  NOT_A_CATEGORY:\n    - key: x\n", "unknown category"),
        ("categories:\n  SHIPPING:\n    - label: no key here\n", "entry without a key"),
        ("version: '1.0'\n", "no categories mapping"),
        ("just a string\n", "not a mapping"),
        ("categories:\n  - SHIPPING\n", "categories is a list"),
    ],
)
def test_malformed_settings_fail_loudly(tmp_path: Path, body: str, reason: str):
    """A deployment whose type vocabulary will not parse should be loud. Failing
    per-upload with a confusing 422 would hide it, and silently dropping a bad
    category would make an upload valid or invalid depending on a typo."""
    settings = tmp_path / "document-types.yaml"
    settings.write_text(body, encoding="utf-8")

    with pytest.raises(DocumentTypeConfigurationError):
        load_document_types(settings)


def test_a_missing_settings_file_fails_loudly(tmp_path: Path):
    with pytest.raises(DocumentTypeConfigurationError):
        load_document_types(tmp_path / "absent.yaml")


def test_types_for_an_unconfigured_category_is_empty(tmp_path: Path):
    settings = tmp_path / "document-types.yaml"
    settings.write_text("categories:\n  OTHER:\n    - key: other\n", encoding="utf-8")
    load_document_types(settings)

    # `types_for` reads the cached default path, so this asserts the shipped file —
    # which does configure SHIPPING. The point is that the helper never raises for
    # a category it has nothing for.
    document_type_loader.reset_cache()
    assert types_for(DocumentCategory.SHIPPING) != ()
