import re
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.factor_service import SEED_PATH
from app.models import AuditLog, EmissionFactor
from app.seed import SeedConflictError, load_seed, read_rows


def _factor(db, key) -> EmissionFactor:
    return db.scalars(select(EmissionFactor).where(EmissionFactor.factor_key == key)).one()


def test_every_seed_row_has_todo_verify_comment_and_source():
    text = SEED_PATH.read_text(encoding="utf-8")
    # Each "- key:" entry must be preceded (within its comment block) by the TODO marker.
    blocks = re.split(r"\n(?=  # TODO: verify against latest published edition)", text)
    keyed_blocks = [b for b in blocks if "- key:" in b]
    assert sum(b.count("- key:") for b in keyed_blocks) == len(read_rows())
    for b in keyed_blocks:
        assert b.count("- key:") == 1, "every factor needs its own TODO comment"
        assert b.lstrip().startswith("# TODO: verify against latest published edition")
    for row in read_rows():
        assert row["source_url"].startswith("https://"), row["key"]
        assert row["publication_year"] >= 2006, row["key"]
        for p in row["published"]:
            assert isinstance(p["value"], str), f"{row['key']}: quote values so YAML doesn't make floats"


def test_seed_loads_and_is_idempotent(db):
    assert load_seed(db) == {"created": 40, "unchanged": 0, "recalculation": {"calculated": 0, "unchanged": 0, "error": 0}}
    assert load_seed(db) == {"created": 0, "unchanged": 40}
    assert db.scalar(select(func.count()).select_from(EmissionFactor)) == 40
    assert db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.actor == "seed")) == 40


@pytest.mark.parametrize(
    ("key", "unit", "expected", "basis", "scope"),
    [
        # 0.727 tCO2/MWh = 727 kg CO2/MWh; CEA is CO2-only.
        ("IN-CEA-GRID-FY2023-24", "MWh", "727", "CO2", 2),
        # 770.9 lb/MWh x 0.45359237 kg/lb
        ("US-EGRID2023-USAVG", "MWh", "349.674358033", "CO2e", 2),
        # 53.06 kg CO2 + 1.0 g CH4 x 28 + 0.10 g N2O x 265
        ("US-EPA-HUB-NATGAS-MMBTU", "MMBtu", "53.1145", "CO2e", 1),
        # 56100 + 1 x 28 + 0.1 x 265 kg per TJ
        ("IN-IPCC2006-NATGAS-MFG", "TJ", "56154.5", "CO2e", 1),
        ("UK-DESNZ-ELEC-2025", "kWh", "0.177", "CO2e", 2),
        ("UK-DESNZ-NATGAS-KWH-2026", "kWh", "0.18231", "CO2e", 1),
    ],
)
def test_seeded_values_derive_correctly(seeded_db, key, unit, expected, basis, scope):
    f = _factor(seeded_db, key)
    assert f.unit == unit
    assert Decimal(f.kgco2e_per_unit) == Decimal(expected)
    assert f.ghg_basis == basis
    assert f.scope == scope
    assert f.derivation


def test_changed_seed_value_without_version_bump_is_refused(db, tmp_path):
    load_seed(db)
    tampered = SEED_PATH.read_text(encoding="utf-8").replace('value: "0.727"', 'value: "0.700"')
    path = tmp_path / "seed.yaml"
    path.write_text(tampered, encoding="utf-8")
    with pytest.raises(SeedConflictError, match="IN-CEA-GRID-FY2023-24 v1 already exists"):
        load_seed(db, path)


def test_new_seed_version_supersedes_old(db, tmp_path):
    load_seed(db)
    text = SEED_PATH.read_text(encoding="utf-8")
    text += '''
  # TODO: verify against latest published edition
  - key: UK-DESNZ-ELEC-2025
    version: 2
    utility_type: electricity
    region: UK
    per_unit: kWh
    published:
      - {gas: CO2e, value: "0.17800", mass_unit: kg}
    source_name: "test correction"
    source_url: "https://example.org"
    publication_year: 2025
    valid_from: 2025-01-01
    valid_to: 2025-12-31
'''
    path = tmp_path / "seed.yaml"
    path.write_text(text, encoding="utf-8")
    assert load_seed(db, path)["created"] == 1
    v1, v2 = db.scalars(select(EmissionFactor).where(EmissionFactor.factor_key == "UK-DESNZ-ELEC-2025")
                        .order_by(EmissionFactor.version)).all()
    assert v1.superseded_by == v2.id
    assert v2.superseded_by is None
