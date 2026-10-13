"""Run the extraction pipeline on PDF files from the command line, without the database.

    python -m app.pipeline.cli bill1.pdf bill2.pdf       # text + LLM extraction + validation
    python -m app.pipeline.cli --text-only bill.pdf      # just the text layer / OCR output

Account-mapping, duplicate-period and outlier checks need facility history, so they only
run in the full app.
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from app.config import get_settings
from app.pipeline.errors import PipelineError
from app.pipeline.llm import LangChainExtractor, extract_structured
from app.pipeline.text import extract_text
from app.pipeline.validate import ValidationContext, validate


def run(path: Path, text_only: bool, extractor: LangChainExtractor | None) -> bool:
    print(f"\n### {path.name}")
    try:
        pdf_text = extract_text(path.read_bytes())
        print(f"text: {pdf_text.method}, {len(pdf_text.pages)} page(s), "
              f"{sum(len(p) for p in pdf_text.pages)} chars")
        if text_only:
            print(pdf_text.as_prompt())
            return True
        result = extract_structured(extractor, pdf_text.as_prompt())
        print(f"model: {result.model_used} (attempts: {result.attempts})")
        print(json.dumps(result.data.model_dump(mode="json"), indent=2))
        s = get_settings()
        ctx = ValidationContext(
            today=date.today(), confidence_threshold=s.review_confidence_threshold,
            max_period_days=s.max_billing_period_days, outlier_ratio=s.outlier_ratio,
            outlier_min_history=s.outlier_min_history,
        )
        v = validate(result.data, pdf_text.pages, ctx)
        if v.quantity_formula:
            print(f"quantity: {v.quantity_formula} {v.canonical_unit or ''}")
        if v.passed:
            print("validation: PASSED (would be auto-approved, subject to account mapping)")
        else:
            print("validation: NEEDS REVIEW")
            for i in v.issues:
                print(f"  - [{i.code}] {i.message}")
        return True
    except PipelineError as e:
        print(f"FAILED: {e}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pdfs", nargs="+", type=Path)
    parser.add_argument("--text-only", action="store_true")
    args = parser.parse_args()
    extractor = None if args.text_only else LangChainExtractor()
    results = [run(p, args.text_only, extractor) for p in args.pdfs]
    print(f"\n{sum(results)}/{len(results)} processed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
