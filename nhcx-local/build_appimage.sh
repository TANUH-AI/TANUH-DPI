#!/bin/bash
# ============================================================================
# build_appimage.sh -- Build an AppImage for nhcx-extract
#
# This script creates a self-contained AppImage that bundles:
#   - Python 3.10 runtime
#   - All pip dependencies (langchain, docling, langgraph, etc.)
#   - nhcx-local source code + rulebooks
#   - CLI entry point
#
# Usage:
#   chmod +x build_appimage.sh
#   ./build_appimage.sh
#
# Output:
#   nhcx-extract-1.0.0-x86_64.AppImage
#
# Requirements:
#   - Linux x86_64
#   - Python 3.10+
#   - pip
#   - wget
#   - fuse (for appimagetool)
# ============================================================================

set -euo pipefail

APP_NAME="nhcx-extract"
APP_VERSION="1.0.0"
ARCH="x86_64"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="${SCRIPT_DIR}/appimage_build"
APPDIR="${BUILD_DIR}/${APP_NAME}.AppDir"

echo "============================================"
echo "  Building ${APP_NAME} AppImage v${APP_VERSION}"
echo "============================================"
echo ""

# ── Step 0: Clean previous build ────────────────────────────────────────────
echo "[0/6] Cleaning previous build..."
rm -rf "${BUILD_DIR}"
mkdir -p "${BUILD_DIR}"

# ── Step 1: Download appimagetool ───────────────────────────────────────────
APPIMAGETOOL="${BUILD_DIR}/appimagetool"
if [ ! -f "${APPIMAGETOOL}" ]; then
    echo "[1/6] Downloading appimagetool..."
    wget -q -O "${APPIMAGETOOL}" \
        "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
    chmod +x "${APPIMAGETOOL}"
else
    echo "[1/6] appimagetool already present."
fi

# ── Step 2: Create AppDir structure ─────────────────────────────────────────
echo "[2/6] Creating AppDir structure..."
mkdir -p "${APPDIR}/usr/bin"
mkdir -p "${APPDIR}/usr/lib/python3/site-packages"
mkdir -p "${APPDIR}/usr/share/applications"
mkdir -p "${APPDIR}/usr/share/icons/hicolor/scalable/apps"

# ── Step 3: Create virtual environment and install dependencies ─────────────
echo "[3/6] Creating Python environment and installing dependencies..."
echo "       (This may take 5-10 minutes on first run)"

VENV_DIR="${BUILD_DIR}/venv"
python3 -m venv "${VENV_DIR}"
source "${VENV_DIR}/bin/activate"

# Install nhcx-local and all dependencies
# Use CPU-only PyTorch to keep AppImage small (~800MB vs ~5GB with CUDA)
# The GPU LLM inference is handled by Ollama, not by this tool.
pip install --quiet --upgrade pip setuptools wheel
pip install --quiet torch --index-url https://download.pytorch.org/whl/cpu
pip install --quiet "${SCRIPT_DIR}"

echo "       Dependencies installed."

# ── Step 4: Bundle Python + packages into AppDir ────────────────────────────
echo "[4/6] Bundling Python runtime and packages..."

# Copy Python interpreter
PYTHON_BIN="$(which python3)"
PYTHON_REAL="$(readlink -f "${PYTHON_BIN}")"
cp "${PYTHON_REAL}" "${APPDIR}/usr/bin/python3"

# Copy Python standard library
PYTHON_VERSION="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PYTHON_LIB="$(python3 -c 'import sysconfig; print(sysconfig.get_path("stdlib"))')"

mkdir -p "${APPDIR}/usr/lib/python${PYTHON_VERSION}"
echo "       Copying standard library from ${PYTHON_LIB}..."

# Copy stdlib (exclude test directories and large unused modules to save space)
rsync -a --quiet \
    --exclude='test/' \
    --exclude='tests/' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='tkinter/' \
    --exclude='idlelib/' \
    --exclude='turtle*' \
    --exclude='ensurepip/' \
    --exclude='distutils/' \
    "${PYTHON_LIB}/" "${APPDIR}/usr/lib/python${PYTHON_VERSION}/"

# Copy lib-dynload (compiled C modules like _ssl, _hashlib, etc.)
DYNLOAD="$(python3 -c 'import sysconfig; print(sysconfig.get_path("platstdlib"))')/lib-dynload"
if [ -d "${DYNLOAD}" ]; then
    mkdir -p "${APPDIR}/usr/lib/python${PYTHON_VERSION}/lib-dynload"
    cp -a "${DYNLOAD}"/*.so "${APPDIR}/usr/lib/python${PYTHON_VERSION}/lib-dynload/" 2>/dev/null || true
fi

# Copy site-packages (all installed pip packages)
SITE_PACKAGES="$(python3 -c 'import site; print(site.getsitepackages()[0])')"
echo "       Copying site-packages from ${SITE_PACKAGES}..."
rsync -a --quiet \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='pip/' \
    --exclude='pip-*' \
    --exclude='setuptools/' \
    --exclude='setuptools-*' \
    --exclude='wheel/' \
    --exclude='wheel-*' \
    --exclude='_distutils_hack/' \
    --exclude='pkg_resources/' \
    --exclude='nvidia/' \
    --exclude='nvidia-*' \
    --exclude='triton/' \
    --exclude='triton-*' \
    --exclude='torch/test/' \
    --exclude='torch/cuda/' \
    --exclude='torch/_inductor/' \
    --exclude='torch/distributed/' \
    "${SITE_PACKAGES}/" "${APPDIR}/usr/lib/python3/site-packages/"

# Copy shared libraries that Python extensions need
echo "       Copying shared libraries..."
mkdir -p "${APPDIR}/usr/lib/x86_64-linux-gnu"

# Find and copy .so dependencies for key compiled modules
for so_file in $(find "${APPDIR}" -name "*.so" -type f 2>/dev/null); do
    # Get dependencies (|| true to handle .so files ldd can't process)
    ldd "${so_file}" 2>/dev/null | grep "=> /" | awk '{print $3}' | while read dep; do
        dep_name="$(basename "${dep}")"
        # Skip system libraries that are always present
        case "${dep_name}" in
            libc.so*|libm.so*|libpthread.so*|libdl.so*|librt.so*|ld-linux*|libgcc_s*)
                continue ;;
        esac
        if [ ! -f "${APPDIR}/usr/lib/x86_64-linux-gnu/${dep_name}" ]; then
            cp -L "${dep}" "${APPDIR}/usr/lib/x86_64-linux-gnu/" 2>/dev/null || true
        fi
    done || true
done

# ── Step 5: Copy AppImage metadata ─────────────────────────────────────────
echo "[5/6] Adding AppImage metadata..."

# AppRun (entry point)
cp "${SCRIPT_DIR}/appimage/AppRun" "${APPDIR}/AppRun"
chmod +x "${APPDIR}/AppRun"

# Desktop file
cp "${SCRIPT_DIR}/appimage/nhcx-extract.desktop" "${APPDIR}/${APP_NAME}.desktop"
cp "${SCRIPT_DIR}/appimage/nhcx-extract.desktop" "${APPDIR}/usr/share/applications/"

# Icon
cp "${SCRIPT_DIR}/appimage/nhcx-extract.svg" "${APPDIR}/${APP_NAME}.svg"
cp "${SCRIPT_DIR}/appimage/nhcx-extract.svg" "${APPDIR}/usr/share/icons/hicolor/scalable/apps/"

# Fix the PYTHONPATH in AppRun to match actual Python version
sed -i "s|python3/site-packages|python3/site-packages:${APPDIR}/usr/lib/python${PYTHON_VERSION}|g" \
    "${APPDIR}/AppRun" 2>/dev/null || true

deactivate

# ── Step 6: Build the AppImage ──────────────────────────────────────────────
echo "[6/6] Building AppImage..."
echo ""

OUTPUT_FILE="${SCRIPT_DIR}/${APP_NAME}-${APP_VERSION}-${ARCH}.AppImage"

# appimagetool needs ARCH env var
export ARCH="${ARCH}"
APPIMAGE_EXTRACT_AND_RUN=1 "${APPIMAGETOOL}" "${APPDIR}" "${OUTPUT_FILE}" 2>&1 | tail -5

echo ""
echo "============================================"
echo "  BUILD COMPLETE!"
echo "============================================"
echo ""
echo "  Output: ${OUTPUT_FILE}"
echo "  Size:   $(du -sh "${OUTPUT_FILE}" | cut -f1)"
echo ""
echo "  Test it:"
echo "    chmod +x ${OUTPUT_FILE}"
echo "    ./${APP_NAME}-${APP_VERSION}-${ARCH}.AppImage check -m gemma4:26b"
echo "    ./${APP_NAME}-${APP_VERSION}-${ARCH}.AppImage abdm report.pdf -o out.json -m gemma4:26b"
echo ""
