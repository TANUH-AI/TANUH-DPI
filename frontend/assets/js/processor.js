/**
 * processor.js - Shared logic for PDF to FHIR/NHCX conversion
 *
 * Tokens are fetched silently before each upload if not already cached.
 * UI users never need to visit the API Access tab.
 */
(function() {
    "use strict";

    // ── Silent token fetch ─────────────────────────────────────────────────────
    // Fetches a token in the background using a generic guest identity.
    // Stores it in sessionStorage so subsequent uploads reuse it.
    async function ensureToken(isClinical, base) {
        const storageKey = isClinical ? 'abdm_token' : 'nhcx_token';
        const existing   = sessionStorage.getItem(storageKey);
        if (existing) return existing;

        // Try to reuse the developer token generated in the API Access tab
        const centralKey = isClinical ? 'dpi_token_pdf2abdm' : 'dpi_token_pdf2nhcx';
        const central = localStorage.getItem(centralKey);
        if (central) {
            sessionStorage.setItem(storageKey, central);
            return central;
        }

        // Silent centralized token fetch using logged-in Firebase session
        if (window.DPI_Auth && window.DPI_Auth.isLoggedIn()) {
            const firebaseToken = await window.DPI_Auth.getToken();
            const serviceId = isClinical ? 'pdf2abdm' : 'pdf2nhcx';
            const loggerBase = window.DPI_API_CONFIG ? window.DPI_API_CONFIG.logger : 'http://localhost:8002';
            try {
                const r = await fetch(`${loggerBase}/auth/token`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': `Bearer ${firebaseToken}`
                    },
                    body: JSON.stringify({ service: serviceId })
                });
                if (r.ok) {
                    const data = await r.json();
                    sessionStorage.setItem(storageKey, data.access_token);
                    localStorage.setItem(centralKey, data.access_token);
                    localStorage.setItem(`dpi_token_expires_${serviceId}`, data.expires_at);
                    localStorage.setItem(`dpi_token_status_${serviceId}`, data.status);
                    return data.access_token;
                }
            } catch (err) {
                console.error("Silent token retrieval failed:", err);
            }
        }
        return null;
    }

    // ── Main upload entry point ────────────────────────────────────────────────
    async function processFile(taskType) {
        const isClinical = (taskType === 'PDF2FHIR');
        const fileInput  = document.getElementById(isClinical ? 'fileFHIR'           : 'fileNHCX');
        const outputEl   = document.getElementById(isClinical ? 'outputFHIR'         : 'outputNHCX');
        const loader     = document.getElementById(isClinical ? 'loaderFHIR'         : 'loaderNHCX');
        const btn        = document.getElementById(isClinical ? 'btnFHIR'            : 'btnNHCX');
        const logo       = document.getElementById(isClinical ? 'processingLogoFHIR' : 'processingLogoNHCX');

        if (!fileInput.files.length) {
            window.showToast('No File', 'Please select a PDF file.', 'warn');
            return;
        }

        const formData = new FormData();
        formData.append("file",       fileInput.files[0]);
        formData.append("model",      'gemma4');
        formData.append("ocr_engine", 'auto');

        if (window.getDash) {
            const d = window.getDash();
            if (d.last_state) formData.append("state", d.last_state);
            if (d.last_city)  formData.append("city",  d.last_city);
        }

        // UI feedback
        if (logo)   logo.style.display = "block";
        if (outputEl && outputEl.parentElement) outputEl.parentElement.style.display = "none";
        if (loader) loader.style.display = "inline-block";
        if (btn)    btn.disabled = true;
        outputEl.textContent = "Processing...";

        const base = window.DPI_API_CONFIG
            ? (isClinical ? window.DPI_API_CONFIG.abdm : window.DPI_API_CONFIG.nhcx)
            : (window.location.hostname === "localhost"
                ? (isClinical ? "http://localhost:8000" : "http://localhost:8001")
                : window.location.origin);

        // Silently obtain or reuse a token — user never needs to do this manually
        const token   = await ensureToken(isClinical, base);
        const headers = token ? { 'Authorization': `Bearer ${token}` } : {};

        const isLocal = base.includes('localhost') || base.includes('127.0.0.1');

        try {
            if (isLocal) {
                // Sync path for local dev — no GCS / Redis / Celery needed
                const syncUrl = isClinical ? `${base}/pdf2abdm` : `${base}/pdf2nhcx`;
                const r = await fetch(syncUrl, {
                    method: 'POST',
                    body:   formData,
                    headers
                });
                if (r.status === 401) throw new Error("Token rejected by server. Please refresh and try again.");
                if (!r.ok) throw new Error(await _extractErrorMessage(r, `${isClinical ? 'Clinical' : 'Insurance'} processing failed`));
                const data = await r.json();
                renderResult(data, taskType, outputEl, fileInput);
            } else if (!isClinical) {
                // Async path for NHCX (production — uses GCS + Celery)
                // base already includes /pdf2nhcx from DPI_API_CONFIG
                const r = await fetch(`${base}/submit`, {
                    method: 'POST',
                    body:   formData,
                    headers
                });
                if (r.status === 401) throw new Error("Token rejected by server. Please refresh and try again.");
                if (!r.ok) throw new Error(await _extractErrorMessage(r, 'Insurance Policy upload failed'));
                const { task_id } = await r.json();
                const data = await pollTask(task_id, base, headers);
                if (data && (data.status === 'rejected' || data.status === 'failed')) {
                    throw new Error(data.error || 'Processing failed');
                }
                renderResult(data, taskType, outputEl, fileInput);
            } else {
                // Async path for ABDM (production — uses GCS + Celery)
                // base already includes /pdf2abdm from DPI_API_CONFIG
                const r = await fetch(`${base}/submit`, {
                    method: 'POST',
                    body:   formData,
                    headers
                });
                if (r.status === 401) throw new Error("Token rejected by server. Please refresh and try again.");
                if (!r.ok) throw new Error(await _extractErrorMessage(r, 'Clinical Document processing failed'));
                const { task_id } = await r.json();
                const data = await pollAbdmTask(task_id, base, headers);
                if (data && (data.status === 'rejected' || data.status === 'failed')) {
                    throw new Error(data.error || 'Processing failed');
                }
                renderResult(data, taskType, outputEl, fileInput);
            }

            if (window.trackInference) window.trackInference();
        } catch (err) {
            outputEl.textContent = `Error: ${err.message}`;
            if (outputEl.parentElement) outputEl.parentElement.style.display = "block";
            window.showToast('Error', err.message, 'error');
        } finally {
            if (logo)   logo.style.display = "none";
            if (loader) loader.style.display = "none";
            if (btn)    btn.disabled = false;
        }
    }

    /**
     * Extract a human-readable error message from a non-OK HTTP response.
     * Reads the JSON body and prefers detail.message > detail > error > fallback.
     */
    async function _extractErrorMessage(response, fallback) {
        try {
            const body = await response.json();
            // FastAPI structured error: { detail: { title, message } }
            if (body && body.detail) {
                const d = body.detail;
                if (typeof d === 'object' && d.message) {
                    const prefix = d.title ? `${d.title}: ` : '';
                    return `${prefix}${d.message}`;
                }
                if (typeof d === 'string') return d;
            }
            // Generic error field
            if (body && body.error)   return body.error;
            if (body && body.message) return body.message;
        } catch (_) { /* body wasn't JSON */ }
        return `${fallback} (${response.status})`;
    }

    async function _fetchTaskResult(taskId, resultPath, base, headers) {
        const origin = window.location.origin;
        const resultUrl = resultPath.startsWith('http') ? resultPath : `${origin}${resultPath}`;
        const rr = await fetch(resultUrl, { headers });
        if (!rr.ok) throw new Error(`Failed to fetch result (${rr.status})`);
        const bundle = await rr.json();
        if (bundle.status === 'rejected' || bundle.status === 'failed') {
            throw new Error(bundle.error || 'Processing failed');
        }
        return bundle;
    }

    async function pollTask(taskId, base, headers) {
        const statusUrl = `${base}/task-status/${taskId}`;
        while (true) {
            const r = await fetch(statusUrl, { headers });
            const j = await r.json();

            if (j.status === 'completed' || j.status === 'SUCCESS') {
                return await _fetchTaskResult(
                    taskId,
                    j.result_url || `/task-result/${taskId}`,
                    base, headers
                );
            }

            if (j.status === 'rejected') throw new Error(j.error || 'Document type rejected');
            if (j.status === 'FAILURE'  || j.status === 'failed') throw new Error(j.error || 'Task failed');

            await new Promise(res => setTimeout(res, 6000));
        }
    }

    async function pollAbdmTask(taskId, base, headers) {
        const statusUrl = `${base}/task-status/${taskId}`;
        while (true) {
            const r = await fetch(statusUrl, { headers });
            const j = await r.json();

            if (j.status === 'completed' || j.status === 'SUCCESS') {
                return await _fetchTaskResult(
                    taskId,
                    j.result_url || `/task-result/${taskId}`,
                    base, headers
                );
            }

            if (j.status === 'rejected') throw new Error(j.error || 'Document type rejected');
            if (j.status === 'FAILURE'  || j.status === 'failed') throw new Error(j.error || 'Task failed');

            await new Promise(res => setTimeout(res, 6000));
        }
    }


    function renderResult(data, type, outputEl, fileInput) {
        if (outputEl.parentElement) outputEl.parentElement.style.display = "block";

        // Both NHCX and ABDM return a task-result wrapper — unwrap to show bare FHIR.
        // NHCX:  { status, task_id, doc_type, bundle: {...}, ... }
        // ABDM:  { status, task_id, doc_types, bundles: [...], ... }
        let display = data;
        if (data && data.bundle) {
            // NHCX: single bundle stored under "bundle" key
            display = data.bundle;
        } else if (data && data.bundles && Array.isArray(data.bundles)) {
            // ABDM: one bundle per patient; show array or unwrap if single
            display = data.bundles.length === 1 ? data.bundles[0] : data.bundles;
        }

        outputEl.textContent = JSON.stringify(display, null, 2);
        if (window.Prism) Prism.highlightElement(outputEl);
    }



    window.processFile       = processFile;
    window.runFhirValidation = async function(type) {
        window.showToast('Validation', 'Starting FHIR R4 validation...', 'info');
    };

    window.INS_init = function () {
        const landing = document.getElementById('insurance-landing-view');
        const interactive = document.getElementById('insurance-interactive-view');
        if (landing) landing.style.display = 'block';
        if (interactive) interactive.style.display = 'none';
    };

    window.INS_launchService = function () {
        const landing = document.getElementById('insurance-landing-view');
        const interactive = document.getElementById('insurance-interactive-view');
        if (landing) landing.style.display = 'none';
        if (interactive) {
            interactive.style.display = 'block';
            const pendingSub = sessionStorage.getItem('pendingLaunchSubTab');
            let targetBtn = null;
            if (pendingSub) {
                sessionStorage.removeItem('pendingLaunchSubTab');
                targetBtn = interactive.querySelector(`.sub-tab-btn[onclick*="${pendingSub}"]`);
            }
            if (!targetBtn) {
                targetBtn = interactive.querySelector('.sub-tab-btn');
            }
            if (targetBtn) {
                targetBtn.click();
            }
        }
    };

    window.INS_handleFileChange = function () {
        if (window.updateFileName) {
            window.updateFileName('fileNHCX');
        }
        const input = document.getElementById('fileNHCX');
        const dropzone = document.getElementById('insDropzone');
        const card = document.getElementById('insFileCard');
        const nameEl = document.getElementById('insCardFileName');
        const sizeEl = document.getElementById('insCardFileSize');
        const btn = document.getElementById('btnNHCX');
        
        if (input && input.files && input.files.length > 0) {
            const file = input.files[0];
            if (nameEl) nameEl.textContent = file.name;
            if (sizeEl) {
                const sizeMB = (file.size / (1024 * 1024)).toFixed(2);
                sizeEl.textContent = sizeMB + " MB";
            }
            if (dropzone) dropzone.style.display = 'none';
            if (card) card.style.display = 'flex';
            if (btn) btn.removeAttribute('disabled');
        }
    };

    window.INS_removeFile = function (e) {
        if (e) e.stopPropagation();
        const input = document.getElementById('fileNHCX');
        const dropzone = document.getElementById('insDropzone');
        const card = document.getElementById('insFileCard');
        const btn = document.getElementById('btnNHCX');
        
        if (input) {
            input.value = '';
            const span = document.querySelector('#labelNHCX .file-text');
            if (span) span.textContent = 'Choose PDF file...';
        }
        if (dropzone) dropzone.style.display = 'flex';
        if (card) card.style.display = 'none';
        if (btn) btn.setAttribute('disabled', 'true');
        
        const outputEl = document.getElementById('outputNHCX');
        if (outputEl) outputEl.textContent = 'Output will appear here...';
        const info = document.getElementById('infoNHCX');
        if (info) info.style.display = 'none';
        const bundleSelect = document.getElementById('bundleSelectorContainerNHCX');
        if (bundleSelect) bundleSelect.style.display = 'none';
        const logo = document.getElementById('processingLogoNHCX');
        if (logo) logo.style.display = 'none';
        const valReport = document.getElementById('validationReportNHCX');
        if (valReport) valReport.textContent = '';
    };

    window.CLN_init = function () {
        const landing = document.getElementById('clinical-landing-view');
        const interactive = document.getElementById('clinical-interactive-view');
        if (landing) landing.style.display = 'block';
        if (interactive) interactive.style.display = 'none';
    };

    window.AUDIO_init = function () {
        const landing = document.getElementById('audioasr-landing-view');
        const interactive = document.getElementById('audioasr-interactive-view');
        if (landing) landing.style.display = 'block';
        if (interactive) interactive.style.display = 'none';
    };

    window.AUDIO_launchService = function () {
        const landing = document.getElementById('audioasr-landing-view');
        const interactive = document.getElementById('audioasr-interactive-view');
        if (landing) landing.style.display = 'none';
        if (interactive) {
            interactive.style.display = 'block';
            const pendingSub = sessionStorage.getItem('pendingLaunchSubTab');
            let targetBtn = null;
            if (pendingSub) {
                sessionStorage.removeItem('pendingLaunchSubTab');
                targetBtn = interactive.querySelector(`.sub-tab-btn[onclick*="${pendingSub}"]`);
            }
            if (!targetBtn) {
                targetBtn = interactive.querySelector('.sub-tab-btn');
            }
            if (targetBtn) {
                targetBtn.click();
            }
        }
    };

    window.CLN_launchService = function () {
        const landing = document.getElementById('clinical-landing-view');
        const interactive = document.getElementById('clinical-interactive-view');
        if (landing) landing.style.display = 'none';
        if (interactive) {
            interactive.style.display = 'block';
            const pendingSub = sessionStorage.getItem('pendingLaunchSubTab');
            let targetBtn = null;
            if (pendingSub) {
                sessionStorage.removeItem('pendingLaunchSubTab');
                targetBtn = interactive.querySelector(`.sub-tab-btn[onclick*="${pendingSub}"]`);
            }
            if (!targetBtn) {
                targetBtn = interactive.querySelector('.sub-tab-btn');
            }
            if (targetBtn) {
                targetBtn.click();
            }
        }
    };

    window.CLN_handleFileChange = function () {
        if (window.updateFileName) {
            window.updateFileName('fileFHIR');
        }
        const input = document.getElementById('fileFHIR');
        const dropzone = document.getElementById('clnDropzone');
        const card = document.getElementById('clnFileCard');
        const nameEl = document.getElementById('clnCardFileName');
        const sizeEl = document.getElementById('clnCardFileSize');
        const btn = document.getElementById('btnFHIR');
        
        if (input && input.files && input.files.length > 0) {
            const file = input.files[0];
            if (nameEl) nameEl.textContent = file.name;
            if (sizeEl) {
                const sizeMB = (file.size / (1024 * 1024)).toFixed(2);
                sizeEl.textContent = sizeMB + " MB";
            }
            if (dropzone) dropzone.style.display = 'none';
            if (card) card.style.display = 'flex';
            if (btn) btn.removeAttribute('disabled');
        }
    };

    window.CLN_removeFile = function (e) {
        if (e) e.stopPropagation();
        const input = document.getElementById('fileFHIR');
        const dropzone = document.getElementById('clnDropzone');
        const card = document.getElementById('clnFileCard');
        const btn = document.getElementById('btnFHIR');
        
        if (input) {
            input.value = '';
            const span = document.querySelector('#labelFHIR .file-text');
            if (span) span.textContent = 'Choose PDF file...';
        }
        if (dropzone) dropzone.style.display = 'flex';
        if (card) card.style.display = 'none';
        if (btn) btn.setAttribute('disabled', 'true');
        
        const outputEl = document.getElementById('outputFHIR');
        if (outputEl) outputEl.textContent = 'Output will appear here...';
        const info = document.getElementById('infoFHIR');
        if (info) info.style.display = 'none';
        const bundleSelect = document.getElementById('bundleSelectorContainerFHIR');
        if (bundleSelect) bundleSelect.style.display = 'none';
        const logo = document.getElementById('processingLogoFHIR');
        if (logo) logo.style.display = 'none';
        const valReport = document.getElementById('validationReportFHIR');
        if (valReport) valReport.textContent = '';
    };

    function CT_updateProcessButton() {
        const scanInput = document.getElementById('ctScanInput');
        const reportInput = document.getElementById('ctReportInput');
        const btn = document.getElementById('ctProcessBtn');
        if (!btn) return;
        const hasScan = !!(scanInput && scanInput.files && scanInput.files.length > 0);
        const hasReport = !!(reportInput && reportInput.files && reportInput.files.length > 0);
        if (hasScan && hasReport) {
            btn.removeAttribute('disabled');
        } else {
            btn.setAttribute('disabled', 'true');
        }
    }

    const CT_DATATYPE_LABELS = {
        2: 'uint8',
        4: 'int16',
        8: 'int32',
        16: 'float32',
        64: 'float64',
        256: 'int8',
        512: 'uint16',
        768: 'uint32'
    };
    function CT_getReportCheckerEndpoints() {
        return ['https://request-brussels-amaze.ngrok-free.dev/verify'];
    }

    function CT_buildReportCheckerFormData(scanFile, reportFile) {
        const formData = new FormData();
        formData.append('scan_file', scanFile, scanFile.name);
        formData.append('report_file', reportFile, reportFile.name);
        return formData;
    }

    const CT_previewState = {
        activeKind: null,
        reportUrl: null,
        scan: null,
        playTimer: null
    };

    function CT_getSelectedFile(kind) {
        const input = document.getElementById(kind === 'scan' ? 'ctScanInput' : 'ctReportInput');
        if (!input || !input.files || input.files.length === 0) return null;
        return input.files[0];
    }

    function CT_setPreviewHeader(title, meta, iconClass) {
        const titleEl = document.getElementById('ctPreviewTitle');
        const metaEl = document.getElementById('ctPreviewMeta');
        if (titleEl) titleEl.innerHTML = `<i class="${iconClass}"></i> ${title}`;
        if (metaEl) metaEl.textContent = meta || '';
    }

    function CT_showPreviewPane(kind) {
        const panel = document.getElementById('ctUploadPreviewPanel');
        const scanPane = document.getElementById('ctScanPreviewPane');
        const reportPane = document.getElementById('ctReportPreviewPane');
        if (panel) panel.classList.add('active');
        if (scanPane) scanPane.classList.toggle('active', kind === 'scan');
        if (reportPane) reportPane.classList.toggle('active', kind === 'report');
        CT_previewState.activeKind = kind;
    }

    function CT_prepareReportPreview(file) {
        if (CT_previewState.reportUrl) {
            URL.revokeObjectURL(CT_previewState.reportUrl);
        }
        CT_previewState.reportUrl = URL.createObjectURL(file);
        const frame = document.getElementById('ctReportPreviewFrame');
        if (frame && CT_previewState.activeKind === 'report') {
            frame.src = CT_previewState.reportUrl;
        }
    }

    function CT_setPlayButton(isPlaying) {
        const btn = document.getElementById('ctScanPlayBtn');
        if (!btn) return;
        btn.innerHTML = isPlaying
            ? '<i class="fas fa-pause"></i> Pause slices'
            : '<i class="fas fa-play"></i> Play slices';
    }

    function CT_stopScanPlayback() {
        if (CT_previewState.playTimer) {
            window.clearInterval(CT_previewState.playTimer);
            CT_previewState.playTimer = null;
        }
        CT_setPlayButton(false);
    }

    function CT_clearPreview(kind) {
        if (!kind || kind === 'report') {
            if (CT_previewState.reportUrl) {
                URL.revokeObjectURL(CT_previewState.reportUrl);
                CT_previewState.reportUrl = null;
            }
            const frame = document.getElementById('ctReportPreviewFrame');
            if (frame) frame.removeAttribute('src');
        }

        if (!kind || kind === 'scan') {
            CT_stopScanPlayback();
            CT_previewState.scan = null;
            const loading = document.getElementById('ctScanPreviewLoading');
            const viewer = document.getElementById('ctScanPreviewViewer');
            const canvas = document.getElementById('ctScanPreviewCanvas');
            const ctx = canvas ? canvas.getContext('2d') : null;
            if (ctx && canvas) ctx.clearRect(0, 0, canvas.width, canvas.height);
            if (loading) loading.textContent = 'Preparing CT scan preview...';
            if (viewer) viewer.style.display = 'none';
        }

        if (!kind || CT_previewState.activeKind === kind) {
            window.CT_hideUploadPreview();
        }
    }

    function CT_renderSelectedFile(kind) {
        const isScan = kind === 'scan';
        const input = document.getElementById(isScan ? 'ctScanInput' : 'ctReportInput');
        const dropzone = document.getElementById(isScan ? 'ctScanDropzone' : 'ctReportDropzone');
        const card = document.getElementById(isScan ? 'ctScanCard' : 'ctReportCard');
        const nameEl = document.getElementById(isScan ? 'ctScanFileName' : 'ctReportFileName');
        const sizeEl = document.getElementById(isScan ? 'ctScanFileSize' : 'ctReportFileSize');
        if (!input || !input.files || input.files.length === 0) return;

        const file = input.files[0];
        CT_clearPreview(kind);
        if (nameEl) nameEl.textContent = file.name;
        if (sizeEl) {
            sizeEl.textContent = isScan
                ? (file.size / (1024 * 1024)).toFixed(2) + " MB"
                : (file.size / 1024).toFixed(1) + " KB";
        }
        if (dropzone) dropzone.style.display = 'none';
        if (card) card.style.display = 'flex';
        if (!isScan) CT_prepareReportPreview(file);
    }

    async function CT_decompressIfNeeded(file, buffer) {
        const bytes = new Uint8Array(buffer, 0, Math.min(2, buffer.byteLength));
        const isGzip = bytes.length === 2 && bytes[0] === 0x1f && bytes[1] === 0x8b;
        if (!isGzip) return buffer;

        if (!('DecompressionStream' in window)) {
            throw new Error('This browser cannot preview compressed NIfTI files. Upload processing is still available.');
        }

        const stream = new Blob([buffer]).stream().pipeThrough(new DecompressionStream('gzip'));
        return await new Response(stream).arrayBuffer();
    }

    function CT_parseNifti(buffer, fileName) {
        if (buffer.byteLength < 352) {
            throw new Error('NIfTI header is incomplete.');
        }

        const view = new DataView(buffer);
        const littleSize = view.getInt32(0, true);
        const bigSize = view.getInt32(0, false);
        let littleEndian = true;
        if (littleSize !== 348) {
            if (bigSize === 348) {
                littleEndian = false;
            } else {
                throw new Error('Only NIfTI-1 single-file volumes are supported for quick preview.');
            }
        }

        const width = view.getInt16(42, littleEndian);
        const height = view.getInt16(44, littleEndian);
        const depth = Math.max(1, view.getInt16(46, littleEndian));
        const datatype = view.getInt16(70, littleEndian);
        const bitpix = view.getInt16(72, littleEndian);
        const bytes = bitpix / 8;
        const voxOffsetRaw = view.getFloat32(108, littleEndian);
        const voxOffset = Number.isFinite(voxOffsetRaw) && voxOffsetRaw > 0 ? Math.floor(voxOffsetRaw) : 352;
        const slopeRaw = view.getFloat32(112, littleEndian);
        const interceptRaw = view.getFloat32(116, littleEndian);
        const slope = Number.isFinite(slopeRaw) && slopeRaw !== 0 ? slopeRaw : 1;
        const intercept = Number.isFinite(interceptRaw) ? interceptRaw : 0;

        if (!width || !height || width < 1 || height < 1) {
            throw new Error('NIfTI dimensions are invalid.');
        }

        if (!CT_DATATYPE_LABELS[datatype] || !Number.isInteger(bytes) || bytes < 1) {
            throw new Error('This NIfTI datatype is not supported by the lightweight preview.');
        }

        const neededBytes = voxOffset + (width * height * depth * bytes);
        if (neededBytes > buffer.byteLength) {
            throw new Error('NIfTI image data is incomplete.');
        }

        return {
            buffer,
            view,
            fileName,
            littleEndian,
            datatype,
            datatypeLabel: CT_DATATYPE_LABELS[datatype],
            bitpix,
            bytes,
            voxOffset,
            slope,
            intercept,
            width,
            height,
            depth,
            sliceIndex: Math.floor(depth / 2)
        };
    }

    function CT_readVoxel(scan, voxelIndex) {
        const offset = scan.voxOffset + (voxelIndex * scan.bytes);
        let value;
        switch (scan.datatype) {
            case 2:
                value = scan.view.getUint8(offset);
                break;
            case 4:
                value = scan.view.getInt16(offset, scan.littleEndian);
                break;
            case 8:
                value = scan.view.getInt32(offset, scan.littleEndian);
                break;
            case 16:
                value = scan.view.getFloat32(offset, scan.littleEndian);
                break;
            case 64:
                value = scan.view.getFloat64(offset, scan.littleEndian);
                break;
            case 256:
                value = scan.view.getInt8(offset);
                break;
            case 512:
                value = scan.view.getUint16(offset, scan.littleEndian);
                break;
            case 768:
                value = scan.view.getUint32(offset, scan.littleEndian);
                break;
            default:
                value = 0;
        }
        return (value * scan.slope) + scan.intercept;
    }

    function CT_getSliceValues(scan, sliceIndex) {
        const safeSlice = Math.max(0, Math.min(scan.depth - 1, sliceIndex));
        const values = new Float32Array(scan.width * scan.height);
        const sliceOffset = safeSlice * scan.width * scan.height;
        for (let i = 0; i < values.length; i++) {
            values[i] = CT_readVoxel(scan, sliceOffset + i);
        }
        return values;
    }

    function CT_getPreviewWindow(values) {
        const sample = [];
        const stride = Math.max(1, Math.floor(values.length / 20000));
        for (let i = 0; i < values.length; i += stride) {
            const value = values[i];
            if (Number.isFinite(value)) sample.push(value);
        }
        if (sample.length < 2) return { low: 0, high: 1 };
        sample.sort((a, b) => a - b);
        let low = sample[Math.floor(sample.length * 0.01)];
        let high = sample[Math.floor(sample.length * 0.99)];
        if (!Number.isFinite(low) || !Number.isFinite(high) || high <= low) {
            low = sample[0];
            high = sample[sample.length - 1];
        }
        if (high <= low) high = low + 1;
        return { low, high };
    }

    function CT_escapeHtml(value) {
        return String(value).replace(/[&<>"']/g, ch => ({
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#39;'
        }[ch]));
    }

    function CT_paintSlice(scan, sliceIndex) {
        const canvas = document.getElementById('ctScanPreviewCanvas');
        if (!canvas) return;

        const safeSlice = Math.max(0, Math.min(scan.depth - 1, sliceIndex));
        scan.sliceIndex = safeSlice;
        const values = CT_getSliceValues(scan, safeSlice);
        const windowRange = CT_getPreviewWindow(values);
        canvas.width = scan.width;
        canvas.height = scan.height;

        const ctx = canvas.getContext('2d');
        const image = ctx.createImageData(scan.width, scan.height);
        const denom = windowRange.high - windowRange.low;
        for (let i = 0; i < values.length; i++) {
            const normalized = (values[i] - windowRange.low) / denom;
            const gray = Math.max(0, Math.min(255, Math.round(normalized * 255)));
            const pixel = i * 4;
            image.data[pixel] = gray;
            image.data[pixel + 1] = gray;
            image.data[pixel + 2] = gray;
            image.data[pixel + 3] = 255;
        }
        ctx.putImageData(image, 0, 0);

        const label = document.getElementById('ctScanSliceLabel');
        if (label) label.textContent = `${safeSlice + 1} / ${scan.depth}`;
        const slider = document.getElementById('ctScanSliceSlider');
        if (slider && slider.value !== String(safeSlice)) slider.value = String(safeSlice);
        const meta = document.getElementById('ctScanPreviewMeta');
        if (meta) {
            meta.innerHTML = `<strong>${CT_escapeHtml(scan.fileName)}</strong>${scan.width} x ${scan.height} x ${scan.depth}<br>${scan.datatypeLabel}, ${scan.bitpix}-bit<br>Window ${windowRange.low.toFixed(1)} to ${windowRange.high.toFixed(1)}`;
        }
    }

    async function CT_loadScanPreview(file) {
        const loading = document.getElementById('ctScanPreviewLoading');
        const viewer = document.getElementById('ctScanPreviewViewer');
        if (loading) {
            loading.style.display = 'flex';
            loading.textContent = 'Preparing CT scan preview...';
        }
        if (viewer) viewer.style.display = 'none';

        const compressedBuffer = await file.arrayBuffer();
        const buffer = await CT_decompressIfNeeded(file, compressedBuffer);
        const scan = CT_parseNifti(buffer, file.name);
        CT_previewState.scan = scan;

        const slider = document.getElementById('ctScanSliceSlider');
        if (slider) {
            slider.min = '0';
            slider.max = String(Math.max(0, scan.depth - 1));
            slider.value = String(scan.sliceIndex);
        }
        CT_paintSlice(scan, scan.sliceIndex);

        if (loading) loading.style.display = 'none';
        if (viewer) viewer.style.display = 'grid';
    }

    window.CT_renderScanSlice = function (sliceIndex) {
        if (!CT_previewState.scan) return;
        CT_paintSlice(CT_previewState.scan, sliceIndex);
    };

    window.CT_toggleScanPlayback = function () {
        if (!CT_previewState.scan) return;

        if (CT_previewState.playTimer) {
            CT_stopScanPlayback();
            return;
        }

        CT_setPlayButton(true);
        CT_previewState.playTimer = window.setInterval(() => {
            const scan = CT_previewState.scan;
            if (!scan || CT_previewState.activeKind !== 'scan') {
                CT_stopScanPlayback();
                return;
            }
            const nextSlice = scan.sliceIndex >= scan.depth - 1 ? 0 : scan.sliceIndex + 1;
            CT_paintSlice(scan, nextSlice);
        }, 180);
    };

    window.CT_showUploadPreview = async function (kind, e) {
        if (e) e.stopPropagation();
        const file = CT_getSelectedFile(kind);
        if (!file) {
            if (window.showToast) window.showToast('No File', 'Please select a file first.', 'warn');
            return;
        }

        CT_showPreviewPane(kind);
        if (kind === 'report') {
            CT_stopScanPlayback();
            if (!CT_previewState.reportUrl) CT_prepareReportPreview(file);
            const frame = document.getElementById('ctReportPreviewFrame');
            if (frame) frame.src = CT_previewState.reportUrl;
            CT_setPreviewHeader('Report PDF Preview', file.name, 'fas fa-file-pdf');
            return;
        }

        CT_setPreviewHeader('CT Scan Preview', file.name, 'fas fa-x-ray');
        try {
            if (CT_previewState.scan && CT_previewState.scan.fileName === file.name) {
                const loading = document.getElementById('ctScanPreviewLoading');
                const viewer = document.getElementById('ctScanPreviewViewer');
                if (loading) loading.style.display = 'none';
                if (viewer) viewer.style.display = 'grid';
                CT_paintSlice(CT_previewState.scan, CT_previewState.scan.sliceIndex);
            } else {
                await CT_loadScanPreview(file);
            }
        } catch (err) {
            const loading = document.getElementById('ctScanPreviewLoading');
            const viewer = document.getElementById('ctScanPreviewViewer');
            if (viewer) viewer.style.display = 'none';
            if (loading) {
                loading.style.display = 'flex';
                loading.textContent = err.message || 'Unable to preview this NIfTI file.';
            }
        }
    };

    window.CT_hideUploadPreview = function () {
        const panel = document.getElementById('ctUploadPreviewPanel');
        const scanPane = document.getElementById('ctScanPreviewPane');
        const reportPane = document.getElementById('ctReportPreviewPane');
        if (panel) panel.classList.remove('active');
        if (scanPane) scanPane.classList.remove('active');
        if (reportPane) reportPane.classList.remove('active');
        CT_previewState.activeKind = null;
        CT_stopScanPlayback();
    };

    function CT_clearResultTags() {
        const pass = document.getElementById('ctResultPass');
        const review = document.getElementById('ctResultReview');
        if (pass) pass.classList.remove('ct-result-pass-active');
        if (review) review.classList.remove('ct-result-review-active');
    }

    function CT_showResultTagColors() {
        const pass = document.getElementById('ctResultPass');
        const review = document.getElementById('ctResultReview');
        if (pass) pass.classList.add('ct-result-pass-active');
        if (review) review.classList.add('ct-result-review-active');
    }

    function CT_getPredictionDecision(prediction) {
        const normalized = String(prediction || '').trim().toUpperCase();
        const compact = normalized.replace(/[^A-Z]/g, '');
        if (compact === 'PASS' || compact === 'YES') return 'PASS';
        if (compact === 'REVIEW' || compact === 'NEEDSREVIEW') return 'REVIEW';
        return '';
    }

    function CT_getPredictionLabel(prediction) {
        const decision = CT_getPredictionDecision(prediction);
        if (decision === 'PASS') return 'PASS';
        if (decision === 'REVIEW') return 'Needs Review';
        return '';
    }

    function CT_showPredictionTag(prediction) {
        const decision = CT_getPredictionDecision(prediction);
        const pass = document.getElementById('ctResultPass');
        const review = document.getElementById('ctResultReview');
        CT_clearResultTags();

        if (decision === 'PASS' && pass) {
            pass.classList.add('ct-result-pass-active');
        } else if (decision === 'REVIEW' && review) {
            review.classList.add('ct-result-review-active');
        }
    }

    function CT_formatApiResult(data) {
        const label = CT_getPredictionLabel(data && data.prediction);
        const details = [];

        if (data && Number.isFinite(Number(data.latency_seconds))) {
            details.push(`Latency: ${Number(data.latency_seconds).toFixed(2)}s`);
        }

        if (!label) return 'Prediction unavailable from API';
        return `${label}${details.length ? ': ' + details.join(' | ') : ''}`;
    }

    async function CT_submitToReportChecker(scanFile, reportFile) {
        let lastError = null;
        const endpoints = CT_getReportCheckerEndpoints();

        for (const endpoint of endpoints) {
            try {
                const response = await fetch(endpoint, {
                    method: 'POST',
                    body: CT_buildReportCheckerFormData(scanFile, reportFile)
                });

                if (response.ok) return await response.json();

                const message = response.status === 501
                    ? `CT proxy route is not active at ${endpoint}.`
                    : await _extractErrorMessage(response, 'CT report checker request failed');
                lastError = new Error(message);

                if (response.status !== 501 && response.status !== 404) {
                    throw lastError;
                }
            } catch (err) {
                lastError = err;
            }
        }

        throw new Error(
            `Unable to reach CT report checker backend. Tried: ${endpoints.join(', ')}. Last error: ${lastError ? lastError.message : 'unknown error'}`
        );
    }

    window.CT_init = function () {
        const landing = document.getElementById('ctreportchecker-landing-view');
        const interactive = document.getElementById('ctreportchecker-interactive-view');
        if (landing) landing.style.display = 'block';
        if (interactive) interactive.style.display = 'none';
        CT_clearResultTags();
        window.CT_hideUploadPreview();
        CT_updateProcessButton();
    };

    window.CT_launchService = function () {
        const landing = document.getElementById('ctreportchecker-landing-view');
        const interactive = document.getElementById('ctreportchecker-interactive-view');
        if (landing) landing.style.display = 'none';
        if (interactive) {
            interactive.style.display = 'block';
            window.scrollTo(0, 0);
        }
        CT_updateProcessButton();
    };

    window.CT_handleFileChange = function (kind) {
        CT_renderSelectedFile(kind);
        CT_updateProcessButton();
    };

    window.CT_removeFile = function (kind, e) {
        if (e) e.stopPropagation();
        const isScan = kind === 'scan';
        const input = document.getElementById(isScan ? 'ctScanInput' : 'ctReportInput');
        const dropzone = document.getElementById(isScan ? 'ctScanDropzone' : 'ctReportDropzone');
        const card = document.getElementById(isScan ? 'ctScanCard' : 'ctReportCard');
        const nameEl = document.getElementById(isScan ? 'ctScanFileName' : 'ctReportFileName');
        const sizeEl = document.getElementById(isScan ? 'ctScanFileSize' : 'ctReportFileSize');

        if (input) input.value = '';
        if (dropzone) dropzone.style.display = 'flex';
        if (card) card.style.display = 'none';
        if (nameEl) nameEl.textContent = isScan ? 'No scan selected' : 'No report selected';
        if (sizeEl) sizeEl.textContent = isScan ? '0 MB' : '0 KB';
        CT_clearPreview(kind);
        CT_clearResultTags();
        CT_updateProcessButton();
    };

    window.CT_processCase = async function () {
        const scanFile = CT_getSelectedFile('scan');
        const reportFile = CT_getSelectedFile('report');
        const btn = document.getElementById('ctProcessBtn');
        const result = document.getElementById('ctResultText');

        if (!scanFile || !reportFile) {
            if (window.showToast) window.showToast('Missing Files', 'Please select both CT scan and report PDF.', 'warn');
            return;
        }

        CT_clearResultTags();
        const originalHtml = btn ? btn.innerHTML : '';
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Checking...';
        }
        if (result) result.textContent = 'Checking scan-report consistency...';

        try {
            const data = await CT_submitToReportChecker(scanFile, reportFile);
            CT_showPredictionTag(data.prediction);
            if (result) result.textContent = CT_formatApiResult(data);
            if (window.showToast) {
                const prediction = CT_getPredictionLabel(data.prediction);
                window.showToast('CT Report Checker', prediction ? `Prediction: ${prediction}` : 'Prediction unavailable from API', 'info', 5000);
            }
            const _logUrl = (window.DPI_API_CONFIG && window.DPI_API_CONFIG.logger)
                ? `${window.DPI_API_CONFIG.logger}/log`
                : (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
                    ? 'http://localhost:8002/log'
                    : `${window.location.origin}/session-logger/log`;
            fetch(_logUrl, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ service: 'ct_report_checker' }) }).catch(() => {});
        } catch (err) {
            if (result) result.textContent = `Error: ${err.message}`;
            if (window.showToast) window.showToast('Error', err.message, 'error');
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = originalHtml;
            }
        }
    };

})();
