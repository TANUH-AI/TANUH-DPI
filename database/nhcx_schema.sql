-- ============================================================
-- NHCX Session Logger — Database Schema
-- Target:  Cloud SQL (34.14.140.183:3306)
-- Run once:  mysql -h 34.14.140.183 -u <user> -p < database/nhcx_schema.sql
-- ============================================================

CREATE DATABASE IF NOT EXISTS nhcx CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE nhcx;

CREATE TABLE IF NOT EXISTS session_logs (
    id              BIGINT         AUTO_INCREMENT PRIMARY KEY,
    session_id      VARCHAR(36)    NOT NULL UNIQUE COMMENT 'UUID v4 generated per request',
    service         ENUM('pdf2abdm', 'pdf2nhcx') NOT NULL COMMENT 'Which pipeline produced this log',
    filename        VARCHAR(512)   COMMENT 'Original uploaded PDF filename',
    document_type   VARCHAR(128)   COMMENT 'Classified doc type (e.g. diagnostic_report, nhcx_claim)',
    model_used      VARCHAR(64)    COMMENT 'LLM model identifier (e.g. gemma4)',
    ocr_engine_used VARCHAR(64)    COMMENT 'OCR engine used (e.g. docling, auto)',
    processing_time FLOAT          COMMENT 'End-to-end processing time in seconds',
    gcs_uri         TEXT           COMMENT 'GCS URI of the uploaded source PDF',
    bundle_count    TINYINT        DEFAULT 1 COMMENT 'Number of FHIR bundles returned',
    status          ENUM('success', 'failed') NOT NULL DEFAULT 'success',
    error_message   TEXT           COMMENT 'Populated only when status = failed',
    client_ip       VARCHAR(64)    COMMENT 'Public IP of the end user',
    created_at      TIMESTAMP      DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_service    (service),
    INDEX idx_status     (status),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
