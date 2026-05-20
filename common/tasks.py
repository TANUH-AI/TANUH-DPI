import os
import asyncio
import logging
from pathlib import Path
from common.celery_app import celery_app
from common.ocr_service import extract_pdf_to_markdown
from common.classifier import classify_document_text

logger = logging.getLogger(__name__)

@celery_app.task(bind=True)
def process_document_task(self, pdf_path: str, model: str = "gemma4"):
    """
    Background task to process a PDF:
    1. OCR (Waterfall)
    2. Classify (Clinical vs Insurance)
    3. Extract (FHIR vs NHCX)
    """
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(self.async_process(pdf_path, model))

async def async_process(self, pdf_path: str, model: str):
    path = Path(pdf_path)
    if not path.exists():
        return {"status": "error", "message": f"File not found: {pdf_path}"}

    # 1. OCR
    self.update_state(state="PROGRESS", meta={"step": "OCR", "progress": 20})
    ocr_result = await extract_pdf_to_markdown(path)
    if ocr_result.is_empty:
        return {"status": "error", "message": "OCR produced no text."}

    # 2. Classify
    self.update_state(state="PROGRESS", meta={"step": "Classifying", "progress": 40})
    category = await classify_document_text(ocr_result.markdown)
    
    # 3. Route & Extract
    self.update_state(state="PROGRESS", meta={"step": f"Extracting ({category})", "progress": 60})
    
    result = {
        "category": category,
        "ocr_engine": ocr_result.engine_used,
        "page_count": ocr_result.page_count,
        "warnings": ocr_result.warnings,
    }

    try:
        if category == "CLINICAL":
            # Lazy import to avoid circular dependencies or heavy init
            from pdf2abdm.utils.llm_requirements import run_abdm_pipeline
            # We need to adapt run_abdm_pipeline to take markdown or we pass the PDF
            # Currently it takes extracted_text.
            # Wait, ocr_service_problem_2 uses Docling internally. We should adapt it to use our ocr_result.
            
            # For now, let's assume we pass the markdown
            # We'll need to update the pipelines to accept pre-extracted text
            bundle = run_abdm_pipeline(
                extracted_text=ocr_result.markdown,
                clinical_artifact="DiagnosticReportRecord", # Default or detect?
                selected_other_resources=[],
                output_dir="/app/fhir_results_problem_2",
                pdf_base64=None, # Task can handle this
                idx=0,
                model=model
            )
            result["bundle"] = bundle
            
        elif category == "INSURANCE":
            from pdf2nhcx.utils.llm_requirements import run_nhcx_insurance_pipeline
            bundle = run_nhcx_insurance_pipeline(
                distilled_text=ocr_result.markdown,
                clinical_artifact="InsurancePlanBundle",
                selected_other_resources=[],
                output_dir="/app/nhcx_results_problem_3",
                pdf_base64=None,
                idx=0,
                model=model
            )
            result["bundle"] = bundle
        else:
            return {"status": "error", "message": f"Invalid document category: {category}", "ocr_text": ocr_result.markdown[:500]}

        self.update_state(state="PROGRESS", meta={"step": "Completed", "progress": 100})
        return {"status": "success", "data": result}

    except Exception as e:
        logger.exception(f"Pipeline error: {e}")
        return {"status": "error", "message": str(e)}

# Inject async_process into process_document_task for easier binding
process_document_task.async_process = async_process
