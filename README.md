# DPI Integrated

This repository contains the DPI Integrated website and microservice platform for healthcare document processing, privacy filtering, and document forgery detection. It is designed as a modular, privacy-preserving system that can run locally or in containerized deployment.

## Overview

The project includes the following main services:

- `pdf2abdm/` — Clinical document extraction service that converts clinical PDFs (diagnostic reports, discharge summaries, lab reports) into ABDM/NHCX-compatible HL7 FHIR Document Bundles.
- `pdf2nhcx/` — Insurance document extraction service that converts insurance policies into NHCX InsurancePlanBundle structured FHIR data.
- `forgensic/` — Document forgery detection service using classical computer vision methods for explainable tampering detection.
- `privacy_filter/` — Privacy filter application that detects and redacts PII from uploaded files using `openai/privacy-filter`.
- `frontend/` — Web UI for interacting with the services and uploading documents.
- `common/` — Shared utilities, OCR orchestration, classification, logging, and Celery task configuration.
- `session_logger/` — Session logging service for capturing usage and request metadata.
- `worker/` — Shared worker container definitions used by the Celery background processes.

## Key Features

- Privacy-first architecture: local OCR, local LLM orchestration, and zero external data leakage.
- Structured FHIR generation: resource-level extraction with ABDM and NHCX rulebook guidance.
- Multi-service orchestration: separate dedicated services for clinical extraction, insurance extraction, forgery detection, and PII redaction.
- Docker Compose deployment: single stack with Redis, API services, workers, frontend, and logger.
- Document classification gate: automatically categorizes uploads as CLINICAL, INSURANCE, or INVALID.
- Multi-patient grouping: groups pages by patient for multi-page lab batch reports in the clinical pipeline.

## Services and docs

### Clinical Extraction — `pdf2abdm`

- Converts clinical PDFs to ABDM/NHCX FHIR Document Bundles.
- Uses OCR, document classification, dynamic workflow orchestration, and dependency-aware resource extraction.
- Read more in `README_ClinicalDocument.md`.

### Insurance Extraction — `pdf2nhcx`

- Converts insurance policy PDFs to NHCX InsurancePlanBundle.
- Uses text distillation and rulebook-driven LLM extraction for insurance structures.
- Read more in `README_InsurancePolicy.md`.

### Forgery Detection — `forgensic`

- Detects document forgery using explainable classical computer vision techniques.
- Supports detection categories such as copy-paste, overwrite, added content, erasure, merge, watermark removal, and more.
- Read more in `README_ForgeryDetection.md`.

### Privacy Filter — `privacy_filter`

- Detects and redacts personal information from uploaded documents.
- Supports text, PDF, image, DOCX, CSV, and DICOM file formats.
- Read more in `README_PrivacyFilter.md`.

## Deployment

A Docker Compose stack is provided in `docker-compose.yml` to start the full platform locally. The stack includes:

- `redis` for Celery broker/backend
- `pdf2abdm` and `pdf2nhcx` API services
- `celery-abdm-worker` and `celery-nhcx-worker`
- `frontend` web UI service
- `session-logger` service
- `privacy-filter` redaction service
- `forgensic` forgery detection service

### Quick start

1. Copy `.env` and configure credentials if needed.
2. Run `docker-compose up --build`.
3. Access services on configured ports.

## Repository contents

- `pdf2abdm/` — clinical extraction microservice
- `pdf2nhcx/` — insurance extraction microservice
- `forgensic/` — forgery detection microservice
- `privacy_filter/` — privacy redaction microservice
- `frontend/` — website frontend
- `common/` — shared utilities and services
- `session_logger/` — request/session logger
- `worker/` — Celery worker container definitions
- `README_ProblemStatement_2.md` — problem statement documentation for ABDM clinical extraction
- `README_ProblemStatement_3.md` — problem statement documentation for NHCX insurance extraction

## Notes

- The system is designed for local, offline execution and can be adapted for deployment on private infrastructure.
- The repository contains multiple independent engines and reuseable service components to support a unified website experience.

---

For full details on each component, refer to the individual README files present at the repository root.
