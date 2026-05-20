# NHCX Local -- Extract FHIR Bundles from PDFs Locally

A command-line tool that extracts **HL7 FHIR R4 Bundles** from clinical and insurance PDFs using a **local LLM** (via [Ollama](https://ollama.com)). All data stays on your machine -- fully confidential, no cloud API calls.

## What It Does

| Input | Output | Pipeline |
|-------|--------|----------|
| Clinical PDF (Discharge Summary, Lab Report) | ABDM-compliant FHIR Bundle (JSON) | `nhcx-extract abdm` |
| Insurance PDF (Policy Document, Claim) | NHCX-compliant FHIR Bundle (JSON) | `nhcx-extract nhcx` |
| Any PDF | Auto-detected FHIR Bundle | `nhcx-extract auto` |

## System Requirements

| Requirement | Minimum | Recommended |
|-------------|---------|-------------|
| **RAM** | 8 GB | 16 GB+ |
| **GPU VRAM** | 4 GB (for small models) | 8 GB+ (for gemma3) |
| **Disk** | 10 GB free | 20 GB free |
| **Python** | 3.10+ | 3.11+ |
| **OS** | Linux, macOS, Windows | Linux with NVIDIA GPU |

> **Note:** CPU-only inference works but is significantly slower (10-30x). A GPU with 8GB+ VRAM is strongly recommended.

### Processing Time Benchmarks (gemma4:26b)

*Estimated average extraction time per document using the larger 26B parameter model:*

| Hardware / Deployment | Processing Time |
|-----------------------|-----------------|
| **NVIDIA RTX A6000** | ~9 minutes |
| **NVIDIA RTX A6000 Ada** | ~8 minutes |
| **NVIDIA GB10** | ~12 minutes |
| **Google Vertex (Cloud MaaS LLM)** | ~2 minutes |

---

## Installation

### Step 1: Install Ollama

Ollama runs the LLM locally on your machine.

**Linux:**
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

**macOS:**
```bash
brew install ollama
```

**Windows:**
Download from https://ollama.com/download

### Step 2: Pull a Model

```bash
# Recommended: Gemma 3 (good balance of quality and speed)
ollama pull gemma3

# Alternative: Smaller/faster model (less accurate)
ollama pull llama3.1:8b

# Alternative: Larger model (more accurate, needs more VRAM)
ollama pull gemma2:27b
```

### Step 3: Install nhcx-local

**Option A: Install from source (recommended for hackathon)**
```bash
cd nhcx-local
pip install -e .
```

**Option B: Install directly from GitHub**
```bash
pip install git+https://github.com/tanuh-bcd/NHCX_HACKATHON.git#subdirectory=nhcx-local
```

**Option C: Standalone Executables (No Python required)**
If you do not want to install Python or pip, you can download a single executable file:
- **Linux (x86_64 AppImage):** [Download](https://drive.google.com/file/d/1Jb-KK6i1bTNtJ9731zMX8MBcMXfcWalI/view?usp=sharing)
- **Linux (ARM64 Binary):** [Download](https://drive.google.com/file/d/16t_R4U3emX9DswYferLZwRtKHjgHP2YB/view?usp=sharing)
- **Windows (x86_64 EXE):** [Download](https://drive.google.com/file/d/16rnbuXTHooIWeh4R_2OmxLBNOnbjHt7D/view?usp=sharing)
- **macOS (Universal Binary):** [Download](https://drive.google.com/file/d/1Lf6Mbydg_KCnPS-xKkDRwqVuvkFaQgYW/view?usp=sharing)

After downloading, unzip and make the file executable (Linux/macOS):
```bash
# Linux x86_64
chmod +x nhcx-extract-1.0.0-x86_64.AppImage
./nhcx-extract-1.0.0-x86_64.AppImage check

# Linux ARM64 (aarch64)
chmod +x nhcx-extract-linux-aarch64
./nhcx-extract-linux-aarch64 check
```

### Step 4: Verify Installation

```bash
# Check that Ollama is running and the model is available
nhcx-extract check

# You should see:
#   OK: Ollama is running. Model 'gemma3' is available.
```

---

## Usage

### Extract from a Clinical Document (ABDM)

```bash
# Discharge summary
nhcx-extract abdm discharge_summary.pdf

# Lab report with custom output path
nhcx-extract abdm lab_report.pdf -o result.json

# Use a different model
nhcx-extract abdm report.pdf -m llama3.1:8b

# Verbose mode (see all LLM calls)
nhcx-extract abdm report.pdf -v
```

### Extract from an Insurance Document (NHCX)

```bash
# Insurance policy
nhcx-extract nhcx insurance_policy.pdf

# With custom output
nhcx-extract nhcx policy.pdf -o nhcx_bundle.json
```

### Auto-detect Document Type

```bash
# Let the tool figure out if it's clinical or insurance
nhcx-extract auto document.pdf
```

### Check System Health

```bash
# Verify Ollama + model are ready
nhcx-extract check

# Check a specific model
nhcx-extract check -m gemma2:27b
```

---

## Command Reference

### `nhcx-extract abdm <pdf_path>`

Extract FHIR bundle from a clinical document.

| Option | Description |
|--------|-------------|
| `-o, --output` | Output JSON file path (default: `<input>_fhir.json`) |
| `-m, --model` | Ollama model name (default: `gemma3`) |
| `-v, --verbose` | Enable verbose logging |
| `--no-embed-pdf` | Don't embed the PDF in DocumentReference |

### `nhcx-extract nhcx <pdf_path>`

Extract FHIR bundle from an insurance document.

Same options as `abdm`.

### `nhcx-extract auto <pdf_path>`

Auto-detect document type and extract.

Same options as `abdm`.

### `nhcx-extract check`

Check Ollama health and model availability.

| Option | Description |
|--------|-------------|
| `-m, --model` | Specific model to check |

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `NHCX_MODEL` | `gemma3` | Default LLM model |

### Using a Remote Ollama Server

If Ollama is running on a different machine (e.g., a GPU server):

```bash
export OLLAMA_BASE_URL=http://192.168.1.100:11434
nhcx-extract abdm report.pdf
```

---

## Output Format

The tool outputs standard **HL7 FHIR R4 JSON Bundles**.

### Clinical (ABDM) Output Structure
```json
{
  "resourceType": "Bundle",
  "type": "document",
  "meta": {
    "profile": ["https://nrces.in/ndhm/fhir/r4/StructureDefinition/DocumentBundle"]
  },
  "entry": [
    { "resource": { "resourceType": "Composition", "..." : "..." } },
    { "resource": { "resourceType": "Patient", "..." : "..." } },
    { "resource": { "resourceType": "Encounter", "..." : "..." } },
    { "resource": { "resourceType": "Condition", "..." : "..." } },
    "..."
  ]
}
```

### Insurance (NHCX) Output Structure
```json
{
  "resourceType": "Bundle",
  "type": "collection",
  "meta": {
    "profile": ["https://nrces.in/ndhm/fhir/r4/StructureDefinition/InsurancePlanBundle"]
  },
  "entry": [
    { "resource": { "resourceType": "InsurancePlan", "..." : "..." } },
    { "resource": { "resourceType": "Organization", "..." : "..." } },
    "..."
  ]
}
```

---

## Troubleshooting

### "Cannot connect to Ollama"

```bash
# Start the Ollama server
ollama serve

# Or check if it's already running
curl http://localhost:11434/api/tags
```

### "Model not found"

```bash
# List available models
ollama list

# Pull the model you need
ollama pull gemma3
```

### Slow performance (CPU-only)

If you don't have a GPU, use a smaller model:

```bash
nhcx-extract abdm report.pdf -m llama3.1:8b
```

### Out of GPU memory

Use a smaller or quantized model:

```bash
ollama pull gemma3:2b    # 2B parameter model, ~2GB VRAM
nhcx-extract abdm report.pdf -m gemma3:2b
```

### OCR issues (scanned PDF)

If text extraction fails, install the full OCR pipeline:

```bash
pip install "nhcx-local[gpu]"
```

This installs PyTorch and Transformers for advanced OCR (Docling with ML-based table detection).

---

## Architecture

```
PDF Input
    |
    v
[OCR Engine]  pypdf (fast) -> docling (high quality)
    |
    v
[Classifier]  keyword screening -> LLM fallback
    |
    v
[LangGraph Workflow]  Topologically sorted resource extraction
    |                  Each FHIR resource type = one LLM call
    |                  Uses StructureDefinition rulebooks for guidance
    v
[FHIR Sanitizer]  Fix hallucinations, validate structure
    |
    v
[Bundle Assembler]  Order resources, link references
    |
    v
JSON Output (FHIR R4 Bundle)
```

---

## Development

```bash
# Clone and install in development mode
git clone https://github.com/tanuh-bcd/NHCX_HACKATHON.git
cd NHCX_HACKATHON/nhcx-local
pip install -e .

# Run from source
python -m nhcx_local.cli abdm test.pdf
```

---

## License

MIT
