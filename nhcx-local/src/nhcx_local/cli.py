"""
cli.py -- Command-line interface for nhcx-local.

Usage:
    nhcx-extract abdm  input.pdf -o output.json     # Clinical documents
    nhcx-extract nhcx  input.pdf -o output.json     # Insurance documents
    nhcx-extract auto  input.pdf -o output.json     # Auto-detect type
    nhcx-extract check                               # Check Ollama & model health
"""

import asyncio
import base64
import json
import logging
import os
import sys
import time
from pathlib import Path

import click

# ── Logging setup ────────────────────────────────────────────────────────────

def setup_logging(verbose: bool):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Suppress noisy libraries
    if not verbose:
        for noisy in ["httpcore", "httpx", "urllib3", "google", "grpc"]:
            logging.getLogger(noisy).setLevel(logging.WARNING)


def _get_rulebook_dir(doc_type: str) -> str:
    """Find the rulebook directory, checking package data first, then project root."""
    # Check if running from installed package
    pkg_dir = Path(__file__).parent / "rulebooks" / doc_type
    if pkg_dir.is_dir() and any(pkg_dir.glob("*.json")):
        return str(pkg_dir)

    # Check project root (development mode)
    project_root = Path(__file__).parent.parent.parent.parent
    if doc_type == "abdm":
        candidate = project_root / "pdf2abdm" / "rulebooks_updated"
    else:
        candidate = project_root / "pdf2nhcx" / "rulebooks_updated"

    if candidate.is_dir() and any(candidate.glob("*.json")):
        return str(candidate)

    click.echo(click.style(f"WARNING: Rulebook directory not found for '{doc_type}'.", fg="yellow"))
    click.echo(f"  Looked in: {pkg_dir}")
    click.echo(f"  Looked in: {candidate}")
    click.echo("  Extraction will work but without structure guidance (lower quality).")
    return str(pkg_dir)


def _read_pdf_base64(pdf_path: str) -> str:
    """Read PDF and return base64 encoded string."""
    with open(pdf_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


# ── Main CLI Group ───────────────────────────────────────────────────────────

@click.group()
@click.version_option(version="1.0.0", prog_name="nhcx-extract")
def main():
    """
    NHCX Local -- Extract FHIR bundles from PDFs using a local LLM.

    All processing happens on YOUR machine. No data leaves your computer.

    \b
    Quick start:
      1. Install Ollama:       https://ollama.com/download
      2. Pull a model:         ollama pull gemma3
      3. Extract clinical PDF: nhcx-extract abdm discharge.pdf -o result.json
      4. Extract insurance PDF: nhcx-extract nhcx policy.pdf -o result.json
    """
    pass


# ── Check Command ────────────────────────────────────────────────────────────

@main.command()
@click.option("--model", "-m", default=None, help="Ollama model to check (default: gemma3)")
def check(model):
    """Check if Ollama is running and the model is available."""
    from nhcx_local.llm import check_ollama_health

    click.echo("Checking Ollama status...")
    healthy, message = check_ollama_health(model)

    if healthy:
        click.echo(click.style(f"  OK: {message}", fg="green"))
    else:
        click.echo(click.style(f"  FAILED:", fg="red"))
        for line in message.split("\n"):
            click.echo(f"    {line}")
        sys.exit(1)


# ── ABDM Command ─────────────────────────────────────────────────────────────

@main.command()
@click.argument("pdf_path", type=click.Path(exists=True))
@click.option("--output", "-o", default=None, help="Output JSON file path (default: <input>_fhir.json)")
@click.option("--model", "-m", default=None, help="Ollama model name (default: gemma3)")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
@click.option("--no-embed-pdf", is_flag=True, help="Don't embed the PDF in DocumentReference")
def abdm(pdf_path, output, model, verbose, no_embed_pdf):
    """Extract FHIR bundle from a clinical document (Discharge Summary / Diagnostic Report).

    \b
    Examples:
      nhcx-extract abdm discharge_summary.pdf
      nhcx-extract abdm lab_report.pdf -o result.json -m gemma3
    """
    setup_logging(verbose)
    _run_abdm(pdf_path, output, model, no_embed_pdf)


def _run_abdm(pdf_path, output, model, no_embed_pdf):
    from nhcx_local.llm import check_ollama_health

    # Pre-flight check
    healthy, msg = check_ollama_health(model)
    if not healthy:
        click.echo(click.style("Ollama is not ready:", fg="red"))
        for line in msg.split("\n"):
            click.echo(f"  {line}")
        sys.exit(1)

    click.echo(click.style("ABDM Clinical Document Extraction", fg="cyan", bold=True))
    click.echo(f"  Input:  {pdf_path}")

    if output is None:
        stem = Path(pdf_path).stem
        output = f"{stem}_fhir.json"
    click.echo(f"  Output: {output}")

    # Step 1: OCR
    click.echo("\n[1/4] Extracting text from PDF...")
    start = time.perf_counter()

    from nhcx_local.ocr import extract_pdf_to_markdown, split_markdown_into_pages
    from nhcx_local.pipelines.abdm import (
        is_lab_report_pdf, group_pages_by_patient,
        classify_document, run_abdm_pipeline,
    )
    from nhcx_local.classifier import classify_document_text

    ocr_result = asyncio.run(extract_pdf_to_markdown(Path(pdf_path)))
    pages_text = split_markdown_into_pages(ocr_result.markdown)
    click.echo(f"       Extracted {ocr_result.page_count} pages using {ocr_result.engine_used}")

    pdf_base64 = None if no_embed_pdf else _read_pdf_base64(pdf_path)

    # Group patients
    if is_lab_report_pdf(pages_text):
        click.echo("       Detected multi-patient lab report -- grouping by patient")
        patient_texts = group_pages_by_patient(pages_text)
    else:
        click.echo("       Detected single-patient document")
        patient_texts = ["\n\n".join(pages_text)]

    click.echo(f"       {len(patient_texts)} patient(s) identified")

    # Step 2: Document type validation
    click.echo("\n[2/4] Validating document type...")
    combined_text = "\n".join(patient_texts)
    doc_category = classify_document_text(combined_text)
    click.echo(f"       Category: {doc_category}")

    if doc_category == "INSURANCE":
        click.echo(click.style("       This looks like an insurance document. Use 'nhcx-extract nhcx' instead.", fg="yellow"))
        sys.exit(1)
    if doc_category == "INVALID":
        click.echo(click.style("       This doesn't appear to be a clinical or insurance document.", fg="red"))
        sys.exit(1)

    # Step 3: Process each patient
    click.echo("\n[3/4] Processing with local LLM...")
    rulebook_dir = _get_rulebook_dir("abdm")
    all_bundles = []

    for i, patient_text in enumerate(patient_texts):
        click.echo(f"       Patient {i+1}/{len(patient_texts)}...")

        doc_type, must_resources, selected_other_resources = classify_document(patient_text, model=model)
        click.echo(f"       Document type: {doc_type}")
        click.echo(f"       Resources: {len(must_resources)} mandatory + {len(selected_other_resources)} additional")

        bundle = run_abdm_pipeline(
            extracted_text=patient_text,
            clinical_artifact=doc_type,
            selected_other_resources=selected_other_resources,
            rulebook_dir=rulebook_dir,
            pdf_base64=pdf_base64,
            idx=i,
            model=model,
        )
        all_bundles.append(bundle)

    # Step 4: Save output
    click.echo("\n[4/4] Saving output...")
    elapsed = round(time.perf_counter() - start, 1)

    if len(all_bundles) == 1:
        result = all_bundles[0]
    else:
        result = {"bundles": all_bundles, "patient_count": len(all_bundles)}

    with open(output, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    entry_count = sum(len(b.get("entry", [])) for b in all_bundles)
    click.echo(click.style(f"\n  Done! {entry_count} FHIR resources extracted in {elapsed}s", fg="green", bold=True))
    click.echo(f"  Output saved to: {output}")


# ── NHCX Command ─────────────────────────────────────────────────────────────

@main.command()
@click.argument("pdf_path", type=click.Path(exists=True))
@click.option("--output", "-o", default=None, help="Output JSON file path (default: <input>_fhir.json)")
@click.option("--model", "-m", default=None, help="Ollama model name (default: gemma3)")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
@click.option("--no-embed-pdf", is_flag=True, help="Don't embed the PDF in DocumentReference")
def nhcx(pdf_path, output, model, verbose, no_embed_pdf):
    """Extract FHIR bundle from an insurance document (Insurance Plan / Claim).

    \b
    Examples:
      nhcx-extract nhcx insurance_policy.pdf
      nhcx-extract nhcx policy.pdf -o result.json -m gemma3
    """
    setup_logging(verbose)
    _run_nhcx(pdf_path, output, model, no_embed_pdf)


def _run_nhcx(pdf_path, output, model, no_embed_pdf):
    from nhcx_local.llm import check_ollama_health

    # Pre-flight check
    healthy, msg = check_ollama_health(model)
    if not healthy:
        click.echo(click.style("Ollama is not ready:", fg="red"))
        for line in msg.split("\n"):
            click.echo(f"  {line}")
        sys.exit(1)

    click.echo(click.style("NHCX Insurance Document Extraction", fg="cyan", bold=True))
    click.echo(f"  Input:  {pdf_path}")

    if output is None:
        stem = Path(pdf_path).stem
        output = f"{stem}_fhir.json"
    click.echo(f"  Output: {output}")

    start = time.perf_counter()

    # Step 1: OCR
    click.echo("\n[1/5] Extracting text from PDF...")
    from nhcx_local.ocr import extract_pdf_to_markdown
    from nhcx_local.pipelines.nhcx import (
        distill_insurance_text, select_nhcx_resources, run_nhcx_pipeline,
    )
    from nhcx_local.classifier import classify_document_text

    ocr_result = asyncio.run(extract_pdf_to_markdown(Path(pdf_path)))
    click.echo(f"       Extracted {ocr_result.page_count} pages using {ocr_result.engine_used}")

    pdf_base64 = None if no_embed_pdf else _read_pdf_base64(pdf_path)

    # Step 2: Distill insurance text
    click.echo("\n[2/5] Distilling insurance text (this may take a few minutes)...")
    distilled_text = distill_insurance_text(ocr_result.markdown, model=model)
    click.echo(f"       Distilled {len(ocr_result.markdown)} -> {len(distilled_text)} chars")

    # Step 3: Validate document type
    click.echo("\n[3/5] Validating document type...")
    doc_category = classify_document_text(distilled_text)
    click.echo(f"       Category: {doc_category}")

    if doc_category == "CLINICAL":
        click.echo(click.style("       This looks like a clinical document. Use 'nhcx-extract abdm' instead.", fg="yellow"))
        sys.exit(1)
    if doc_category == "INVALID":
        click.echo(click.style("       This doesn't appear to be an insurance document.", fg="red"))
        sys.exit(1)

    # Step 4: Process
    click.echo("\n[4/5] Processing with local LLM...")
    rulebook_dir = _get_rulebook_dir("nhcx")

    doc_type, must_resources, selected_other_resources = select_nhcx_resources(distilled_text, model=model)
    click.echo(f"       Artifact: {doc_type}")
    click.echo(f"       Resources: {len(must_resources)} mandatory + {len(selected_other_resources)} additional")

    bundle = run_nhcx_pipeline(
        distilled_text=distilled_text,
        clinical_artifact=doc_type,
        selected_other_resources=selected_other_resources,
        rulebook_dir=rulebook_dir,
        pdf_base64=pdf_base64,
        idx=0,
        model=model,
    )

    # Step 5: Save output
    click.echo("\n[5/5] Saving output...")
    elapsed = round(time.perf_counter() - start, 1)

    with open(output, "w", encoding="utf-8") as f:
        json.dump(bundle, f, indent=2, ensure_ascii=False)

    entry_count = len(bundle.get("entry", []))
    click.echo(click.style(f"\n  Done! {entry_count} FHIR resources extracted in {elapsed}s", fg="green", bold=True))
    click.echo(f"  Output saved to: {output}")


# ── Auto Command ─────────────────────────────────────────────────────────────

@main.command()
@click.argument("pdf_path", type=click.Path(exists=True))
@click.option("--output", "-o", default=None, help="Output JSON file path (default: <input>_fhir.json)")
@click.option("--model", "-m", default=None, help="Ollama model name (default: gemma3)")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
@click.option("--no-embed-pdf", is_flag=True, help="Don't embed the PDF in DocumentReference")
def auto(pdf_path, output, model, verbose, no_embed_pdf):
    """Auto-detect document type and extract FHIR bundle.

    \b
    Automatically determines whether the PDF is a clinical document
    or an insurance document and routes to the correct pipeline.

    \b
    Examples:
      nhcx-extract auto document.pdf
      nhcx-extract auto document.pdf -o result.json
    """
    setup_logging(verbose)

    click.echo(click.style("Auto-detect Mode", fg="cyan", bold=True))
    click.echo(f"  Input: {pdf_path}")

    # Quick OCR for classification
    click.echo("\n  Extracting text for classification...")
    from nhcx_local.ocr import extract_pdf_to_markdown
    from nhcx_local.classifier import classify_document_text

    ocr_result = asyncio.run(extract_pdf_to_markdown(Path(pdf_path)))

    doc_category = classify_document_text(ocr_result.markdown)
    click.echo(f"  Detected: {doc_category}")

    if doc_category == "CLINICAL":
        click.echo("  Routing to ABDM pipeline...\n")
        _run_abdm(pdf_path, output, model, no_embed_pdf)
    elif doc_category == "INSURANCE":
        click.echo("  Routing to NHCX pipeline...\n")
        _run_nhcx(pdf_path, output, model, no_embed_pdf)
    else:
        click.echo(click.style("\n  Could not determine document type.", fg="red"))
        click.echo("  Please specify manually: nhcx-extract abdm <file> OR nhcx-extract nhcx <file>")
        sys.exit(1)


if __name__ == "__main__":
    main()
