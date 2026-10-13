"""Load emission factors from seed/emission_factors.yaml.

    python -m app.seed            # load into DATABASE_URL
    python -m app.seed --check    # validate the YAML only, no database

Idempotent: rows whose (key, version) already exist are skipped, but only if their values
are unchanged. A changed value under an existing version is an error; bump the version.
"""

import argparse
import sys
from decimal import Decimal
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calc.service import recalculate
from app.factor_service import SEED_PATH, add_factor, build_factor, spec_from_seed_row
from app.models import EmissionFactor


class SeedConflictError(RuntimeError):
    pass


def read_rows(path: Path = SEED_PATH) -> list[dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["factors"]


def load_seed(db: Session, path: Path = SEED_PATH) -> dict[str, int]:
    stats = {"created": 0, "unchanged": 0}
    for row in read_rows(path):
        spec = spec_from_seed_row(row)
        existing = db.scalars(
            select(EmissionFactor).where(
                EmissionFactor.factor_key == spec.key, EmissionFactor.version == spec.version
            )
        ).first()
        if existing is not None:
            fresh = build_factor(spec, created_by="seed")
            if Decimal(existing.kgco2e_per_unit) != fresh.kgco2e_per_unit or existing.unit != fresh.unit:
                raise SeedConflictError(
                    f"{spec.key} v{spec.version} already exists with a different value "
                    f"({existing.kgco2e_per_unit} vs {fresh.kgco2e_per_unit}). Add version {spec.version + 1} instead."
                )
            stats["unchanged"] += 1
            continue
        add_factor(db, spec, actor="seed")
        stats["created"] += 1
    if stats["created"]:
        # New or corrected global factors: bring every approved bill up to date.
        stats["recalculation"] = recalculate(db, actor="seed", reason="emission factor seed loaded")
    db.commit()
    return stats


def check(path: Path = SEED_PATH) -> int:
    rows = read_rows(path)
    for row in rows:
        f = build_factor(spec_from_seed_row(row), created_by="seed")
        print(f"{f.factor_key:<28} {f.region:<8} {format(f.kgco2e_per_unit.normalize(), 'f'):>14} kg {f.ghg_basis}/{f.unit}")
    print(f"{len(rows)} factors OK")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="validate the seed file without a database")
    args = parser.parse_args()
    if args.check:
        return check()

    from app.db import SessionLocal

    with SessionLocal() as db:
        stats = load_seed(db)
    print(f"Emission factors: {stats['created']} created, {stats['unchanged']} already present")
    if "recalculation" in stats:
        print(f"Approved bills recalculated: {stats['recalculation']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
