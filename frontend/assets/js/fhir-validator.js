/**
 * FHIR Validator — Client-side FHIR R4 validation
 * Uses HL7's public FHIR validator API (validator.fhir.org)
 * and annotates a line-numbered JSON viewer with error tiles.
 */

// ─── Helpers ─────────────────────────────────────────────────────────────────

function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

const IMPORTANT_RESOURCES = new Set([
    'AllergyIntolerance', 'Appointment', 'Binary', 'CarePlan', 'ChargeItem', 'Condition', 
    'DiagnosticReportImaging', 'DiagnosticReportLab', 'DiagnosticReportRecord', 
    'DischargeSummaryRecord', 'DocumentBundle', 'DocumentReference', 'Encounter', 
    'FamilyMemberHistory', 'ImagingStudy', 'ImmunizationRecommendation', 'Immunization', 
    'Invoice', 'Media', 'MedicationRequest', 'MedicationStatement', 'Medication', 
    'ObservationBodyMeasurement', 'ObservationGeneralAssessment', 'ObservationLifestyle', 
    'ObservationPhysicalActivity', 'ObservationVitalSigns', 'ObservationWomenHealth', 
    'Observation', 'Organization', 'Patient', 'PractitionerRole', 'Practitioner', 
    'Procedure', 'ServiceRequest', 'Specimen', 'ClaimResponse', 'Claim', 
    'CommunicationRequest', 'Communication', 'CoverageEligibilityRequest', 
    'CoverageEligibilityResponse', 'Coverage', 'InsurancePlanBundle', 'InsurancePlan', 
    'PaymentNotice', 'PaymentReconciliation', 'Task', 'Bundle'
]);

function syntaxHighlightJsonLine(line) {
    if (!line) return ' ';
    
    // 1. Escape HTML for safety
    let escaped = escapeHtml(line);
    
    // 2. Tokenize JSON via Regex
    // This regex looks for strings (capturing potential keys), numbers, booleans, and null
    return escaped.replace(/("(\\u[a-z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/gi, function (match) {
        let cls = 'json-value';
        
        if (/^"/.test(match)) {
            if (/:$/.test(match)) {
                cls = 'json-key';
                const innerText = match.replace(/"/g, '').replace(/:$/, '').trim();
                if (['system', 'text', 'coding', 'cost', 'type'].includes(innerText)) {
                    cls += ` json-key-${innerText}`;
                }
            } else {
                cls = 'json-string';
                // Check if the string content is an "important" resource name
                const innerText = match.replace(/"/g, '').trim();
                // We check if the trimmed inner text matches our important set
                if (IMPORTANT_RESOURCES.has(innerText)) {
                    cls += ' json-important';
                }
            }
        } else if (/true|false/.test(match)) {
            cls = 'json-boolean';
        } else if (/null/.test(match)) {
            cls = 'json-null';
        } else if (/[0-9]/.test(match)) {
            cls = 'json-number';
        }
        
        return `<span class="${cls}">${match}</span>`;
    });
}

// ─── Line-Numbered JSON Viewer ────────────────────────────────────────────────

// Registry: textareaId → { renderLines }
const _lnvRegistry = {};

/**
 * Build a line-numbered JSON viewer for a given textarea element.
 */
function buildLineNumberedViewer(textareaEl) {
    textareaEl.style.display = 'none';

    const wrapper = document.createElement('div');
    wrapper.className = 'lnv-wrapper';
    wrapper.setAttribute('data-for', textareaEl.id);

    const gutterEl = document.createElement('div');
    gutterEl.className = 'lnv-gutter';

    const codeEl = document.createElement('div');
    codeEl.className = 'lnv-code';

    wrapper.appendChild(gutterEl);
    wrapper.appendChild(codeEl);

    textareaEl.insertAdjacentElement('afterend', wrapper);

    function renderLines(jsonText, errorMap) {
        const lines = jsonText.split('\n');
        gutterEl.innerHTML = '';
        codeEl.innerHTML = '';

        lines.forEach((line, i) => {
            const lineNum = i + 1;
            const errs = errorMap ? (errorMap[lineNum] || []) : [];
            const hasError = errs.some(e => e.severity === 'error' || e.severity === 'fatal');
            const hasWarn  = errs.some(e => e.severity === 'warning');
            const hasInfo  = errs.some(e => e.severity === 'information');

            // Gutter cell
            const gutterCell = document.createElement('div');
            gutterCell.className = 'lnv-line-gutter';
            if (hasError)      gutterCell.classList.add('lnv-gutter-error');
            else if (hasWarn)  gutterCell.classList.add('lnv-gutter-warn');
            else if (hasInfo)  gutterCell.classList.add('lnv-gutter-info');

            const numSpan = document.createElement('span');
            numSpan.className = 'lnv-linenum';
            numSpan.textContent = lineNum;
            gutterCell.appendChild(numSpan);

            if (errs.length > 0) {
                const badge = document.createElement('span');
                badge.className = 'lnv-badge';
                badge.textContent = errs.length;
                if (hasError)     badge.classList.add('lnv-badge-error');
                else if (hasWarn) badge.classList.add('lnv-badge-warn');
                else              badge.classList.add('lnv-badge-info');
                gutterCell.appendChild(badge);
            }

            gutterEl.appendChild(gutterCell);

            // Code cell
            const codeCell = document.createElement('div');
            codeCell.className = 'lnv-line-code';
            if (hasError)      codeCell.classList.add('lnv-line-error');
            else if (hasWarn)  codeCell.classList.add('lnv-line-warn');
            else if (hasInfo)  codeCell.classList.add('lnv-line-info');
            codeCell.id = `lnv-line-${textareaEl.id}-${lineNum}`;

            const codeSpan = document.createElement('span');
            codeSpan.className = 'lnv-code-text';
            // Use syntax highlighting here
            codeSpan.innerHTML = line.length ? syntaxHighlightJsonLine(line) : ' ';
            codeCell.appendChild(codeSpan);

            // Inline floating error tile on the line
            if (errs.length > 0) {
                const tile = document.createElement('span');
                tile.className = 'lnv-inline-tile';
                if (hasError)     tile.classList.add('lnv-tile-error');
                else if (hasWarn) tile.classList.add('lnv-tile-warn');
                else              tile.classList.add('lnv-tile-info');

                const icon   = hasError ? '✖' : hasWarn ? '⚠' : 'ℹ';
                const msg    = errs[0].message || '';
                const short  = msg.length > 90 ? msg.substring(0, 90) + '…' : msg;
                tile.innerHTML = `${icon} ${escapeHtml(short)}${errs.length > 1 ? ` <em>(+${errs.length - 1} more)</em>` : ''}`;
                codeCell.appendChild(tile);
            }

            codeEl.appendChild(codeCell);
        });
    }

    // Sync scroll
    codeEl.addEventListener('scroll', () => {
        gutterEl.scrollTop = codeEl.scrollTop;
    });

    return { wrapper, renderLines };
}

function initLineNumberedViewer(textareaId) {
    const ta = document.getElementById(textareaId);
    if (!ta || _lnvRegistry[textareaId]) return;
    const { renderLines } = buildLineNumberedViewer(ta);
    _lnvRegistry[textareaId] = { renderLines };
    const val = ta.value !== undefined ? ta.value : ta.textContent || '';
    if (val) renderLines(val, {});
}

function updateLineNumberedViewer(textareaId, errorMap) {
    const ta = document.getElementById(textareaId);
    if (!ta) return;
    if (!_lnvRegistry[textareaId]) initLineNumberedViewer(textareaId);
    const { renderLines } = _lnvRegistry[textareaId];
    const val = ta.value !== undefined ? ta.value : ta.textContent || '';
    renderLines(val, errorMap || {});
}

// ─── FHIR Validation via HL7 Public API ──────────────────────────────────────

function stripLargeAttachments(obj) {
    if (!obj || typeof obj !== 'object') return;
    if (Array.isArray(obj)) {
        for (let item of obj) stripLargeAttachments(item);
    } else {
        // Strip base64 data from Binary resources (PDF embedded by document_reference_node)
        if (obj.resourceType === 'Binary' && obj.data) {
            obj.data = 'SU5WQUxJRF9QQUxPQUQ='; // "INVALID_PALOAD" in base64 — valid format, small size
        }
        for (let key in obj) {
            if (key === 'attachment' && obj[key] && typeof obj[key] === 'object' && obj[key].data) {
                // Remove huge base64 strings to prevent 413 Request Entity Too Large on HAPI FHIR
                // Must be a valid base64 string to pass FHIR validation
                obj[key].data = 'SU5WQUxJRF9QQUxPQUQ='; // "INVALID_PALOAD" in base64
            } else {
                stripLargeAttachments(obj[key]);
            }
        }
    }
}

async function validateFhirJson(jsonString) {
    // Determine the resource type dynamically (usually Bundle)
    let resourceType = 'Bundle';
    let payloadStr = jsonString;
    
    try { 
        let parsed = JSON.parse(jsonString); 
        
        // Auto-unwrap backend API response wrapper if present
        if (parsed.bundles && Array.isArray(parsed.bundles) && parsed.bundles.length > 0) {
            parsed = parsed.bundles[0];
        } else if (parsed.bundle) {
            parsed = parsed.bundle;
        }
        
        // Strip large attachments so HAPI FHIR Nginx doesn't reject it (which causes CORS fetch errors)
        stripLargeAttachments(parsed);
        
        // Stringify with indentation so HAPI FHIR returns accurate line numbers
        payloadStr = JSON.stringify(parsed, null, 2);
        
        if (parsed.resourceType) resourceType = parsed.resourceType;
    }
    catch (e) {
        return { issues: [{ severity: 'fatal', message: `Invalid JSON: ${e.message}`, location: '$', line: 1 }] };
    }

    const VALIDATOR_URL = `https://hapi.fhir.org/baseR4/${resourceType}/$validate`;

    const response = await fetch(VALIDATOR_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/fhir+json', 'Accept': 'application/fhir+json' },
        body: payloadStr,
        signal: AbortSignal.timeout(60000)
    });

    if (!response.ok && response.status !== 400 && response.status !== 422) {
        // 400 or 422 is normal for validation errors (OperationOutcome)
        const text = await response.text();
        throw new Error(`Validator API ${response.status}: ${text.substring(0, 200)}`);
    }

    const result = await response.json();
    const issues = [];

    // The result should be an OperationOutcome resource
    if (result.resourceType === 'OperationOutcome' && result.issue) {
        for (const issue of result.issue) {
            let line = null;
            for (const ext of (issue.extension || [])) {
                if (ext.url && ext.url.includes('operationoutcome-issue-line') && ext.valueInteger != null) {
                    line = ext.valueInteger;
                }
            }
            const loc = (issue.location || issue.expression || []).join(' > ');
            issues.push({
                severity: issue.severity || 'information',
                message: issue.diagnostics || (issue.details && issue.details.text) || 'Unknown issue',
                location: loc || '$',
                line
            });
        }
    }

    return { issues, raw: result };
}

function findLineByPath(lines, path) {
    if (!path) return null;
    const parts = path.split(/[.\[\]>]+/).filter(Boolean).reverse();
    for (const part of parts) {
        if (!part || /^\d+$/.test(part)) continue;
        const key = `"${part}"`;
        for (let i = 0; i < lines.length; i++) {
            if (lines[i].includes(key)) return i + 1;
        }
    }
    return null;
}

function buildErrorMap(issues, jsonString) {
    const errorMap = {};
    const lines = jsonString.split('\n');

    for (const issue of issues) {
        let lineNum = issue.line;
        if (!lineNum && issue.location && issue.location !== '$') {
            lineNum = findLineByPath(lines, issue.location);
        }
        const key = lineNum || 1;
        if (!errorMap[key]) errorMap[key] = [];
        errorMap[key].push(issue);
    }
    return errorMap;
}

// ─── UI: Validation Report Panel ─────────────────────────────────────────────

function renderFhirReport(issues, container, outputId) {
    if (issues.length === 0) {
        container.innerHTML = `
            <div class="val-success">
                <span class="val-success-icon">✔</span>
                <div>
                    <strong>FHIR Validation Passed</strong>
                    <p>No structural or conformance errors found. This resource is valid FHIR R4.</p>
                </div>
            </div>`;
        return;
    }

    const bySev = { fatal: [], error: [], warning: [], information: [] };
    for (const issue of issues) {
        (bySev[issue.severity] || bySev['information']).push(issue);
    }

    const totalErrors = bySev.fatal.length + bySev.error.length;
    const totalWarn   = bySev.warning.length;
    const totalInfo   = bySev.information.length;

    let html = `
        <div class="val-summary-bar">
            <span class="val-summary-title"><i class="fas fa-stethoscope"></i> FHIR R4 Validation Report</span>
            <div class="val-summary-counts">
                ${totalErrors > 0 ? `<span class="val-count-badge val-count-error">✖ ${totalErrors} Error${totalErrors !== 1 ? 's' : ''}</span>` : ''}
                ${totalWarn   > 0 ? `<span class="val-count-badge val-count-warn">⚠ ${totalWarn} Warning${totalWarn !== 1 ? 's' : ''}</span>` : ''}
                ${totalInfo   > 0 ? `<span class="val-count-badge val-count-info">ℹ ${totalInfo} Note${totalInfo !== 1 ? 's' : ''}</span>` : ''}
            </div>
        </div>
        <div class="val-issues-list">`;

    for (const sev of ['fatal', 'error', 'warning', 'information']) {
        for (const issue of bySev[sev]) {
            const cls  = (sev === 'fatal' || sev === 'error') ? 'val-tile-error' : sev === 'warning' ? 'val-tile-warn' : 'val-tile-info';
            const icon = (sev === 'fatal' || sev === 'error') ? '✖' : sev === 'warning' ? '⚠' : 'ℹ';
            const sevLabel = sev.charAt(0).toUpperCase() + sev.slice(1);
            const lineRef = issue.line
                ? `<a href="#" class="val-tile-lineref" onclick="scrollToViewerLine('${outputId}', ${issue.line}); return false;"><i class="fas fa-map-marker-alt"></i> Line ${issue.line}</a>`
                : '';

            html += `
                <div class="val-issue-tile ${cls}">
                    <div class="val-tile-header">
                        <span class="val-tile-icon">${icon}</span>
                        <span class="val-tile-sev">${sevLabel}</span>
                        ${lineRef}
                    </div>
                    <div class="val-tile-msg">${escapeHtml(issue.message)}</div>
                    ${issue.location && issue.location !== '$' ? `<div class="val-tile-loc"><i class="fas fa-code-branch"></i> <code>${escapeHtml(issue.location)}</code></div>` : ''}
                </div>`;
        }
    }

    html += `</div>`;
    container.innerHTML = html;
}

function scrollToViewerLine(textareaId, lineNum) {
    const lineEl = document.getElementById(`lnv-line-${textareaId}-${lineNum}`);
    if (lineEl) {
        lineEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
        lineEl.classList.add('lnv-line-highlight-flash');
        setTimeout(() => lineEl.classList.remove('lnv-line-highlight-flash'), 2000);
    }
}

// ─── Main Entry Point ─────────────────────────────────────────────────────────

async function runFhirValidation(taskType) {
    console.log(`[FHIR Validator] Starting validation for ${taskType}...`);
    const outputId = taskType === 'PDF2FHIR' ? 'outputFHIR' : 'outputNHCX';
    const reportId = taskType === 'PDF2FHIR' ? 'validationReportFHIR' : 'validationReportNHCX';
    const btnId    = taskType === 'PDF2FHIR' ? 'valBtnFHIR' : 'valBtnNHCX';
    const loaderId = taskType === 'PDF2FHIR' ? 'loaderValFHIR' : 'loaderValNHCX';

    const ta       = document.getElementById(outputId);
    const reportEl = document.getElementById(reportId);
    const btn      = document.getElementById(btnId);
    const loader   = document.getElementById(loaderId);

    const jsonText = ta ? (ta.value !== undefined ? ta.value : ta.textContent || '').trim() : '';
    console.log(`[FHIR Validator] Content length: ${jsonText.length}`);

    if (!jsonText || jsonText.startsWith('Processing') || jsonText.startsWith('Error')) {
        console.warn(`[FHIR Validator] No valid content found in ${outputId}`);
        reportEl.innerHTML = `<div class="val-report-empty"><i class="fas fa-info-circle"></i> No FHIR JSON output found. Please run the conversion first.</div>`;
        return;
    }

    // Ensure viewer is initialized before validation
    initLineNumberedViewer(outputId);

    reportEl.innerHTML = `
        <div class="val-loading">
            <div class="val-spinner"></div>
            <span>Validating against FHIR R4 specification<br><small>Using HL7 FHIR Validator API…</small></span>
        </div>`;
    if (loader) loader.style.display = 'inline-block';
    if (btn)    btn.disabled = true;

    try {
        const { issues } = await validateFhirJson(jsonText);
        console.log(`[FHIR Validator] Received ${issues.length} issues.`);
        const errorMap = buildErrorMap(issues, jsonText);

        updateLineNumberedViewer(outputId, errorMap);
        renderFhirReport(issues, reportEl, outputId);

        // Scroll report into view
        reportEl.scrollIntoView({ behavior: 'smooth', block: 'start' });

    } catch (err) {
        console.error(`[FHIR Validator] Error during validation:`, err);
        let hint = 'Unable to reach the HL7 FHIR validator (hapi.fhir.org).';
        if (err.name === 'AbortError' || err.name === 'TimeoutError') {
            hint = 'Request timed out after 60 s. The HAPI FHIR public server may be slow or down — try again in a moment.';
        } else if (err.message && err.message.includes('413')) {
            hint = 'Bundle payload too large (413). The PDF attachment data was not stripped correctly. Please report this.';
        } else if (err.message && err.message.includes('Failed to fetch')) {
            hint = 'Network error. Possible causes: (1) hapi.fhir.org is down — check <a href="https://hapi.fhir.org" target="_blank">hapi.fhir.org</a>, (2) CORS preflight blocked by the server, or (3) no internet connection.';
        }
        reportEl.innerHTML = `
            <div class="val-issue-tile val-tile-error">
                <div class="val-tile-header"><span class="val-tile-icon">✖</span><span class="val-tile-sev">Connection Error</span></div>
                <div class="val-tile-msg">${escapeHtml(err.message)}</div>
                <div class="val-tile-loc">${hint}</div>
            </div>`;
    } finally {
        if (loader) loader.style.display = 'none';
        if (btn)    btn.disabled = false;
    }
}

// ─── Watch textarea updates from processFile() ───────────────────────────────

function watchTextareaForViewer(textareaId) {
    const ta = document.getElementById(textareaId);
    if (!ta) return;
    let lastValue = ta.value !== undefined ? ta.value : ta.textContent || '';

    console.log(`[FHIR Validator] Starting watcher for ${textareaId}...`);

    // Immediate check if content already exists
    if (lastValue.trim() && !lastValue.startsWith('Processing') && !lastValue.startsWith('Error')) {
        initLineNumberedViewer(textareaId);
    }

    setInterval(() => {
        const currentValue = ta.value !== undefined ? ta.value : ta.textContent || '';
        if (currentValue !== lastValue) {
            console.log(`[FHIR Validator] Change detected in ${textareaId}`);
            lastValue = currentValue;
            const v = currentValue.trim();
            if (v && !v.startsWith('Processing') && !v.startsWith('Error')) {
                updateLineNumberedViewer(textareaId, {});
                // Clear old report on new data
                const suffix = textareaId === 'outputFHIR' ? 'FHIR' : 'NHCX';
                const rpt = document.getElementById(`validationReport${suffix}`);
                if (rpt) rpt.innerHTML = '';
            } else if (!v) {
                // If emptied, maybe revert to textarea or keep empty viewer?
                // For now, if empty, we just hide the viewer and show textarea
                const registry = _lnvRegistry[textareaId];
                if (registry) {
                    const wrapper = document.querySelector(`.lnv-wrapper[data-for="${textareaId}"]`);
                    if (wrapper) wrapper.style.display = 'none';
                    ta.style.display = 'block';
                    delete _lnvRegistry[textareaId];
                }
            }
        }
    }, 400);
}

window.addEventListener('load', () => {
    console.log("[FHIR Validator] Window loaded. Initializing watchers...");
    watchTextareaForViewer('outputFHIR');
    watchTextareaForViewer('outputNHCX');
});
