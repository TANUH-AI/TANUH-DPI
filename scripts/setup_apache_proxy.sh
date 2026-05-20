#!/bin/bash
# =============================================================================
# setup_apache_proxy.sh
# Writes the full Apache2 VirtualHost config for nhcxhackathon.tanuh.ai,
# enables required modules, and restarts Apache2.
# Run automatically by docker-starter.sh after containers are up.
# =============================================================================

set -e

DOMAIN="nhcxhackathon.tanuh.ai"
FRONTEND_PORT="8080"
PDF2ABDM_PORT="8000"          # pdf2abdm container host-mapped port
PDF2NHCX_PORT="8001"          # pdf2nhcx container host-mapped port
SESSION_LOGGER_PORT="8002"    # session-logger container host-mapped port
PRIVACY_FILTER_URL="https://privacy-filter-147901050545.asia-south1.run.app"  # Cloud Run

CONF_FILE="/etc/apache2/sites-available/${DOMAIN}.conf"
PROXY_OPTS="timeout=1500 keepalive=On disablereuse=on retry=0"

echo "▶ Writing Apache VirtualHost config: ${CONF_FILE}"

sudo bash -c "cat > ${CONF_FILE}" <<EOF
<VirtualHost *:80>
    ServerName ${DOMAIN}

    # ── Global timeouts (25 min to cover long PDF processing) ────────────────
    Timeout 1500
    ProxyTimeout 1500
    KeepAlive On
    KeepAliveTimeout 1500

    # ── pdf2abdm (Clinical Document / ABDM FHIR) — port ${PDF2ABDM_PORT} ─────
    # Sync & async endpoints
    ProxyPass        /pdf2abdm/submit-url  http://localhost:${PDF2ABDM_PORT}/pdf2abdm/submit-url  ${PROXY_OPTS}
    ProxyPassReverse /pdf2abdm/submit-url  http://localhost:${PDF2ABDM_PORT}/pdf2abdm/submit-url

    ProxyPass        /pdf2abdm/submit      http://localhost:${PDF2ABDM_PORT}/pdf2abdm/submit      ${PROXY_OPTS}
    ProxyPassReverse /pdf2abdm/submit      http://localhost:${PDF2ABDM_PORT}/pdf2abdm/submit

    ProxyPass        /pdf2abdm/task-status http://localhost:${PDF2ABDM_PORT}/pdf2abdm/task-status ${PROXY_OPTS}
    ProxyPassReverse /pdf2abdm/task-status http://localhost:${PDF2ABDM_PORT}/pdf2abdm/task-status

    ProxyPass        /pdf2abdm/task-result http://localhost:${PDF2ABDM_PORT}/pdf2abdm/task-result ${PROXY_OPTS}
    ProxyPassReverse /pdf2abdm/task-result http://localhost:${PDF2ABDM_PORT}/pdf2abdm/task-result

    ProxyPass        /pdf2abdm/health      http://localhost:${PDF2ABDM_PORT}/pdf2abdm/health      ${PROXY_OPTS}
    ProxyPassReverse /pdf2abdm/health      http://localhost:${PDF2ABDM_PORT}/pdf2abdm/health

    ProxyPass        /pdf2abdm/model-health http://localhost:${PDF2ABDM_PORT}/pdf2abdm/model-health ${PROXY_OPTS}
    ProxyPassReverse /pdf2abdm/model-health http://localhost:${PDF2ABDM_PORT}/pdf2abdm/model-health

    ProxyPass        /pdf2abdm/ocr-health  http://localhost:${PDF2ABDM_PORT}/pdf2abdm/ocr-health  ${PROXY_OPTS}
    ProxyPassReverse /pdf2abdm/ocr-health  http://localhost:${PDF2ABDM_PORT}/pdf2abdm/ocr-health

    ProxyPass        /pdf2abdm/api/token   http://localhost:${PDF2ABDM_PORT}/api/token   ${PROXY_OPTS}
    ProxyPassReverse /pdf2abdm/api/token   http://localhost:${PDF2ABDM_PORT}/api/token

    ProxyPass        /pdf2abdm/validate    http://localhost:${PDF2ABDM_PORT}/validate    ${PROXY_OPTS}
    ProxyPassReverse /pdf2abdm/validate    http://localhost:${PDF2ABDM_PORT}/validate

    ProxyPass        /pdf2abdmurl          http://localhost:${PDF2ABDM_PORT}/pdf2abdmurl           ${PROXY_OPTS}
    ProxyPassReverse /pdf2abdmurl          http://localhost:${PDF2ABDM_PORT}/pdf2abdmurl

    # ── Top-level aliases (no service prefix) ────────────────────────────────
    ProxyPass        /task-status  http://localhost:${PDF2ABDM_PORT}/task-status  ${PROXY_OPTS}
    ProxyPassReverse /task-status  http://localhost:${PDF2ABDM_PORT}/task-status

    ProxyPass        /model-health http://localhost:${PDF2ABDM_PORT}/model-health ${PROXY_OPTS}
    ProxyPassReverse /model-health http://localhost:${PDF2ABDM_PORT}/model-health

    # Catch-all for /pdf2abdm (sync POST + legacy /pdf2fhir alias)
    ProxyPass        /pdf2abdm  http://localhost:${PDF2ABDM_PORT}/pdf2abdm  ${PROXY_OPTS}
    ProxyPassReverse /pdf2abdm  http://localhost:${PDF2ABDM_PORT}/pdf2abdm

    ProxyPass        /pdf2fhir  http://localhost:${PDF2ABDM_PORT}/pdf2fhir  ${PROXY_OPTS}
    ProxyPassReverse /pdf2fhir  http://localhost:${PDF2ABDM_PORT}/pdf2fhir

    # ── pdf2nhcx (Insurance Policy / NHCX) — port ${PDF2NHCX_PORT} ───────────
    # Sync & async endpoints
    ProxyPass        /pdf2nhcx/submit-url  http://localhost:${PDF2NHCX_PORT}/pdf2nhcx/submit-url  ${PROXY_OPTS}
    ProxyPassReverse /pdf2nhcx/submit-url  http://localhost:${PDF2NHCX_PORT}/pdf2nhcx/submit-url

    ProxyPass        /pdf2nhcx/submit      http://localhost:${PDF2NHCX_PORT}/pdf2nhcx/submit      ${PROXY_OPTS}
    ProxyPassReverse /pdf2nhcx/submit      http://localhost:${PDF2NHCX_PORT}/pdf2nhcx/submit

    ProxyPass        /pdf2nhcx/task-status http://localhost:${PDF2NHCX_PORT}/pdf2nhcx/task-status ${PROXY_OPTS}
    ProxyPassReverse /pdf2nhcx/task-status http://localhost:${PDF2NHCX_PORT}/pdf2nhcx/task-status

    ProxyPass        /pdf2nhcx/task-result http://localhost:${PDF2NHCX_PORT}/pdf2nhcx/task-result ${PROXY_OPTS}
    ProxyPassReverse /pdf2nhcx/task-result http://localhost:${PDF2NHCX_PORT}/pdf2nhcx/task-result

    ProxyPass        /pdf2nhcx/health      http://localhost:${PDF2NHCX_PORT}/pdf2nhcx/health      ${PROXY_OPTS}
    ProxyPassReverse /pdf2nhcx/health      http://localhost:${PDF2NHCX_PORT}/pdf2nhcx/health

    ProxyPass        /pdf2nhcx/model-health http://localhost:${PDF2NHCX_PORT}/pdf2nhcx/model-health ${PROXY_OPTS}
    ProxyPassReverse /pdf2nhcx/model-health http://localhost:${PDF2NHCX_PORT}/pdf2nhcx/model-health

    ProxyPass        /pdf2nhcx/ocr-health  http://localhost:${PDF2NHCX_PORT}/pdf2nhcx/ocr-health  ${PROXY_OPTS}
    ProxyPassReverse /pdf2nhcx/ocr-health  http://localhost:${PDF2NHCX_PORT}/pdf2nhcx/ocr-health

    ProxyPass        /pdf2nhcx/api/token   http://localhost:${PDF2NHCX_PORT}/api/token   ${PROXY_OPTS}
    ProxyPassReverse /pdf2nhcx/api/token   http://localhost:${PDF2NHCX_PORT}/api/token

    ProxyPass        /pdf2nhcx/validate    http://localhost:${PDF2NHCX_PORT}/validate    ${PROXY_OPTS}
    ProxyPassReverse /pdf2nhcx/validate    http://localhost:${PDF2NHCX_PORT}/validate

    ProxyPass        /pdf2nhcxurl          http://localhost:${PDF2NHCX_PORT}/pdf2nhcxurl           ${PROXY_OPTS}
    ProxyPassReverse /pdf2nhcxurl          http://localhost:${PDF2NHCX_PORT}/pdf2nhcxurl

    ProxyPass        /ocr-service-problem-3 http://localhost:${PDF2NHCX_PORT}/ocr-service-problem-3 ${PROXY_OPTS}
    ProxyPassReverse /ocr-service-problem-3 http://localhost:${PDF2NHCX_PORT}/ocr-service-problem-3

    # Catch-all for /pdf2nhcx
    ProxyPass        /pdf2nhcx  http://localhost:${PDF2NHCX_PORT}/pdf2nhcx  ${PROXY_OPTS}
    ProxyPassReverse /pdf2nhcx  http://localhost:${PDF2NHCX_PORT}/pdf2nhcx

    # ── privacy-filter (PII Redaction) — Cloud Run ───────────────────────────
    # All /privacy-filter/* requests are forwarded to the deployed Cloud Run service.
    # The /privacy-filter prefix is stripped so the Cloud Run app receives clean paths.
    SSLProxyEngine On
    SSLProxyVerify none
    SSLProxyCheckPeerCN off
    SSLProxyCheckPeerName off

    ProxyPass        /privacy-filter/  ${PRIVACY_FILTER_URL}/  ${PROXY_OPTS}
    RequestHeader set Host "privacy-filter-147901050545.asia-south1.run.app"
    ProxyPassReverse /privacy-filter/  ${PRIVACY_FILTER_URL}/

    # ── session-logger (Stats & Logs) — port ${SESSION_LOGGER_PORT} ──────────
    ProxyPass        /session-logger/  http://localhost:${SESSION_LOGGER_PORT}/  ${PROXY_OPTS}
    ProxyPassReverse /session-logger/  http://localhost:${SESSION_LOGGER_PORT}/

    # ── Frontend (catch-all, MUST be last) ───────────────────────────────────
    ProxyPass        /  http://localhost:${FRONTEND_PORT}/  disablereuse=on
    ProxyPassReverse /  http://localhost:${FRONTEND_PORT}/

    ErrorLog  \${APACHE_LOG_DIR}/${DOMAIN}_error.log
    CustomLog \${APACHE_LOG_DIR}/${DOMAIN}_access.log combined
</VirtualHost>
EOF

echo "▶ Enabling required Apache modules..."
sudo a2enmod proxy proxy_http proxy_https ssl rewrite headers

echo "▶ Enabling site ${DOMAIN}..."
sudo a2ensite "${DOMAIN}"

echo "▶ Testing Apache configuration..."
sudo apache2ctl configtest

echo "▶ Restarting Apache2..."
sudo systemctl restart apache2

echo ""
echo "✅ Apache proxy configuration complete."
echo "   Frontend         : https://${DOMAIN}/"
echo "   pdf2abdm API     : https://${DOMAIN}/pdf2abdm"
echo "   pdf2nhcx API     : https://${DOMAIN}/pdf2nhcx"
echo "   Privacy Filter   : https://${DOMAIN}/privacy-filter/api/health  → Cloud Run"
echo "   PF async submit  : https://${DOMAIN}/privacy-filter/api/submit"
echo "   PF task status   : https://${DOMAIN}/privacy-filter/api/task-status/<id>"
echo "   pdf2abdmurl      : https://${DOMAIN}/pdf2abdmurl"
echo "   pdf2nhcxurl      : https://${DOMAIN}/pdf2nhcxurl"
echo "   Task status      : https://${DOMAIN}/task-status/<id>"
echo "   Model health     : https://${DOMAIN}/model-health?model=gemma4"
