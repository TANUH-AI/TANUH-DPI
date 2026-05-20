# ☁️ AWS Deployment Architecture: NHCX Microservices

This document outlines the production-grade deployment strategy for the NHCX FHIR generation pipeline on AWS. The architecture is designed for high availability, asynchronous processing via message queues, and cost-optimized scaling for both CPU and GPU workloads.

---

## 🏗️ High-Level Infrastructure

| Component | AWS Service | Rationale |
| :--- | :--- | :--- |
| **Orchestration** | Amazon EKS (Kubernetes) | Manages container lifecycle, specialized node groups, and service discovery. |
| **Messaging** | Amazon SQS | Decouples services and ensures message persistence during spikes. |
| **Object Storage** | Amazon S3 | Durable storage for source PDFs and generated FHIR bundles. |
| **Database** | Amazon RDS (PostgreSQL) | Stores job metadata, user feedback, and terminology mappings. |
| **Vector Store** | Amazon OpenSearch / Chroma on EC2 | High-performance neural search for RAG. |
| **Monitoring** | Amazon CloudWatch / Managed Grafana | Unified telemetry, logs, and processing metrics. |

---

## 🛠️ Service-Specific Deployment Strategy

### 1. API & Orchestration Layer
*   **Services:** `PDF-2-NHCX-service`, `Feedback-capture-service`
*   **Deployment:** Standard EKS Pods (m5.large).
*   **Networking:** Application Load Balancer (ALB) for public-facing REST/gRPC endpoints.
*   **Logic:** Validates uploads, persists metadata in RDS, uploads PDF to S3, and pushes job IDs to the `OCR-queue`.

### 2. OCR & Parsing (CPU Workload)
*   **Service:** `OCR service`
*   **Deployment:** EKS Node Group with **Keda (Kubernetes Event-driven Autoscaling)**.
*   **Scaling:** Autoscales based on `OCR-queue` depth. Uses Spot Instances (c6i.xlarge) to reduce costs.
*   **Input:** SQS (OCR-queue) | **Output:** S3 (extracted text) & SQS (rag-queue).

### 3. Inference Layer (GPU Workload)
*   **Services:** `LLM-inference-service` (vLLM), `Embedding-model-inference-service`
*   **Deployment:** Amazon EC2 `g5.2xlarge` or `p4d.24xlarge` instances.
*   **Resource Partitioning:** Use Multi-Instance GPU (MIG) or Docker resource limits to share a high-memory A100/H100 between the LLM and Embedding models.
*   **Communication:** Internal gRPC for low-latency inference calls from the RAG and Orchestration services.

### 4. RAG & Knowledge Retrieval
*   **Services:** `RAG-service`, `Embedding-service`
*   **Deployment:** EKS Pods.
*   **Storage:** Persistent Volume Claims (EBS) or EFS if using a distributed vector DB.
*   **Logic:** Consumes from `rag-queue`, queries vector store, and returns context to the orchestrator for prompt construction.

### 5. Validation & Correction Layer
*   **Services:** `FHIR-bundle-validation-service`, `LLM-validation-service`, `Terminology-correction-service`
*   **Deployment:** Lightweight EKS Pods.
*   **Validation Logic:** Uses Java-based FHIR Validator CLI wrapper for schema checks; queries RDS for insurance-specific terminology mappings.

---

## 🔄 Execution & Message Flow

1.  **User/TPA** sends PDF to `PDF-2-NHCX-service` (ALB).
2.  **Orchestrator** stores entry in RDS and file in S3; enqueues to **SQS: OCR-queue**.
3.  **OCR Service** picks up job, parses, and enqueues to **SQS: RAG-queue**.
4.  **RAG Service** fetches context from Vector Store and enqueues to **SQS: LLM-inference-queue**.
5.  **LLM Service** runs extraction/reasoning and returns structured JSON to the **Orchestrator**.
6.  **Orchestrator** triggers **FHIR Validation Service**.
7.  **Final Bundle** is stored in S3 and availability is signaled via Webhook or API response.

---

## 📈 Monitoring & Feedback (Model Improvement)
*   **Monitoring-dashboard-service:** Aggregates CloudWatch metrics (latency, error rates, queue depth) into a custom React-based operational dashboard.
*   **Model-improvement-layer:** A scheduled AWS Batch job that extracts "negative" feedback from RDS, identifies systematic mapping errors, and triggers a RAG index refresh or prompt template update.

---

## 🔒 Security & Compliance
*   **Data Sovereignty:** All traffic stays within the VPC. No data leaves the AWS region.
*   **Encryption:** KMS for S3 buckets (SSE-KMS) and RDS (at-rest). TLS 1.3 for all internal/external traffic.
*   **Access Control:** IAM Roles for Service Accounts (IRSA) ensures each microservice has the *least privilege* access to S3/SQS/RDS.
