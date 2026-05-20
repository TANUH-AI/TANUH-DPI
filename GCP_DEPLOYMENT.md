# ☁️ GCP Deployment Architecture: NHCX Microservices

This document outlines the production-grade deployment strategy for the NHCX FHIR generation pipeline on Google Cloud Platform (GCP). The architecture emphasizes high-performance GKE clusters, high-throughput messaging via Pub/Sub, and integrated AI/ML services.

---

## 🏗️ High-Level Infrastructure

| Component | GCP Service | Rationale |
| :--- | :--- | :--- |
| **Orchestration** | Google Kubernetes Engine (GKE) | Leading managed K8s with Autopilot for easy scaling and GPU node pools. |
| **Messaging** | Cloud Pub/Sub | Global, scalable messaging for decoupling microservice stages. |
| **Object Storage** | Google Cloud Storage (GCS) | Unified storage for clinical PDFs and generated NHCX bundles. |
| **Database** | Cloud SQL (PostgreSQL) | Managed database for job tracking, feedback, and terminology. |
| **Vector Store** | Vertex AI Vector Search | Managed high-performance vector database for RAG. |
| **Monitoring** | Cloud Monitoring & Logging | Integrated telemetry, error reporting, and dashboarding. |

---

## 🛠️ Service-Specific Deployment Strategy

### 1. API & Orchestration Layer
*   **Services:** `PDF-2-NHCX-service`, `Feedback-capture-service`
*   **Deployment:** GKE Standard or Autopilot (e2-standard-4).
*   **Networking:** Cloud Load Balancing (HTTPS) with Global Anycast IP.
*   **Logic:** Receives uploads, updates Cloud SQL, saves files to GCS, and publishes to the `ocr-task-topic`.

### 2. OCR & Parsing (CPU Workload)
*   **Service:** `OCR service`
*   **Deployment:** GKE Node Group with **Horizontal Pod Autoscaler (HPA)** based on Pub/Sub unacknowledged messages.
*   **Scaling:** Uses Preemptible VMs (n2-highcpu-8) to optimize costs for batch OCR processing.
*   **Input:** Pub/Sub (ocr-task-topic) | **Output:** GCS (parsed text) & Pub/Sub (rag-task-topic).

### 3. Inference Layer (GPU Workload)
*   **Services:** `LLM-inference-service` (vLLM), `Embedding-model-inference-service`
*   **Deployment:** GKE Node Pools with **NVIDIA L4** (cost-effective) or **A100** (high-performance) GPUs.
*   **Inference Engine:** vLLM running on GKE nodes with `gcsfuse` to load model weights directly from GCS.
*   **Resource Sharing:** Use Kubernetes resource requests to partition GPU memory between the LLM and the Embedding model.

### 4. RAG & Knowledge Retrieval
*   **Services:** `RAG-service`, `Embedding-service`
*   **Deployment:** GKE Pods.
*   **Storage:** Vertex AI Vector Search for index management; Cloud SQL for metadata.
*   **Logic:** Retrieves relevant policy clauses and rulebooks; builds the "Fact Sheet" context for the LLM.

### 5. Validation & Correction Layer
*   **Services:** `FHIR-bundle-validation-service`, `LLM-validation-service`, `Terminology-correction-service`
*   **Deployment:** GKE Pods.
*   **Validation Logic:** Local FHIR CLI validation; reasoning-based correction via LLM calls to the inference service.

---

## 🔄 Execution & Message Flow

1.  **Consumer API Call:** PDF sent to `PDF-2-NHCX-service`.
2.  **Initial Ingest:** Metadata saved to Cloud SQL; PDF to GCS; Message to **Pub/Sub: ocr-task-topic**.
3.  **OCR Stage:** OCR Service parses document, writes structured text to GCS, and pushes to **Pub/Sub: rag-task-topic**.
4.  **RAG Stage:** RAG Service retrieves context from Vertex AI Vector Search and pushes to **Pub/Sub: llm-inference-topic**.
5.  **Inference Stage:** LLM Service performs extraction and sends results back to the **Orchestrator**.
6.  **Validation Stage:** Orchestrator triggers **FHIR Validation Service**; results finalized.

---

## 📈 Monitoring & Feedback (Model Improvement)
*   **Monitoring-dashboard-service:** Uses Cloud Monitoring dashboards to visualize Pub/Sub latencies, GKE node utilization, and inference throughput.
*   **Model-improvement-layer:** A **Cloud Run job** or **Workflows** task that periodically analyzes feedback in Cloud SQL to trigger index updates or prompt tuning.

---

## 🔒 Security & Compliance
*   **Identity:** Using **Workload Identity** for fine-grained IAM permissions (no service account keys stored in pods).
*   **Data Residency:** All regional services (GKE, Cloud SQL, GCS) pinned to a specific GCP region (e.g., `asia-south1`).
*   **Encryption:** Customer-Managed Encryption Keys (CMEK) via Cloud KMS for data at rest.
