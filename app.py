"""
Entri Bulk Sharing Links generator.

Flask web app that accepts a CSV of domains, calls the Entri Sharing Links API
for each domain, and returns an XLSX file with the generated links.

Credentials and the config object are supplied per-request from the frontend
form. They live in process memory only for the duration of one request and
are NEVER persisted, logged, or echoed back to the client.

Env vars (ENTRI_APPLICATION_ID, ENTRI_SECRET) are honored as fallbacks if
form fields are blank — useful for single-tenant deploys.
"""

import io
import json
import logging
import os
import uuid
from datetime import datetime

from flask import Flask, render_template, request, send_file, jsonify
from werkzeug.utils import secure_filename

from config import settings, DEFAULT_SHARING_CONFIG_JSON
from entri_client import EntriClient, EntriError
from processor import process_domains_to_xlsx, parse_domains_from_csv


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("entri-bulk")

app = Flask(__name__)
# Cap upload size: CSV + config textarea must fit comfortably.
app.config["MAX_CONTENT_LENGTH"] = settings.MAX_UPLOAD_BYTES + settings.MAX_CONFIG_BYTES + 16 * 1024


@app.route("/", methods=["GET"])
def index():
    """Render the upload form, pre-filling the config textarea."""
    return render_template(
        "index.html",
        default_config=DEFAULT_SHARING_CONFIG_JSON,
        default_flow=settings.ENTRI_SHARING_FLOW,
        # Pre-fill applicationId only if a server-side default exists AND is
        # explicitly opted into via env var. Never leak it by default in a
        # multi-tenant deploy.
        prefill_app_id=(
            settings.ENTRI_APPLICATION_ID
            if os.environ.get("ENTRI_PREFILL_APP_ID", "false").lower() == "true"
            else ""
        ),
    )


@app.route("/health", methods=["GET"])
def health():
    """Lightweight health check for hosting platforms."""
    return jsonify({"status": "ok"})


def _resolve_config(raw_config: str) -> dict:
    """
    Parse the user-supplied JSON config and normalize it.

    Accepts either:
      - the inner config object (e.g. {"prefilledDomain": "...", "dnsRecords": [...]}),
        which is what the frontend's textarea is shaped for.
      - the full request body ({"applicationId": "...", "config": {...}}),
        in which case we unwrap to the inner config.

    Raises ValueError on bad input.
    """
    if not raw_config or not raw_config.strip():
        raise ValueError("config is empty")

    if len(raw_config.encode("utf-8")) > settings.MAX_CONFIG_BYTES:
        raise ValueError(f"config exceeds {settings.MAX_CONFIG_BYTES} bytes")

    try:
        parsed = json.loads(raw_config)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON ({exc.msg} at line {exc.lineno}, col {exc.colno})") from exc

    if not isinstance(parsed, dict):
        raise ValueError("config must be a JSON object")

    # If the user pasted the full body shape, unwrap.
    if "config" in parsed and isinstance(parsed["config"], dict):
        parsed = parsed["config"]

    return parsed


@app.route("/api/generate", methods=["POST"])
def generate():
    """
    Accept a CSV upload + credentials + config, return XLSX with links.

    Form fields (multipart/form-data):
      - file:           the CSV upload (required)
      - application_id: Entri applicationId (required, env fallback)
      - secret:         Entri secret      (required, env fallback)
      - flow:           "connect" or "sell" (optional, default "connect")
      - config:         JSON string for the sharing config (required)
    """
    request_id = str(uuid.uuid4())[:8]
    logger.info("[%s] /api/generate received", request_id)

    # ---- Resolve credentials (form first, env fallback) -------------------
    application_id = (request.form.get("application_id") or "").strip() or settings.ENTRI_APPLICATION_ID
    secret = (request.form.get("secret") or "").strip() or settings.ENTRI_SECRET

    if not application_id or not secret:
        return jsonify({
            "error": "Missing credentials. Provide applicationId and secret in the form."
        }), 400

    # ---- Sharing flow ------------------------------------------------------
    flow = (request.form.get("flow") or settings.ENTRI_SHARING_FLOW).strip().lower()
    if flow not in ("connect", "sell"):
        return jsonify({"error": f"Invalid flow '{flow}'. Use 'connect' or 'sell'."}), 400

    # ---- Sharing config ----------------------------------------------------
    raw_config = request.form.get("config") or ""
    try:
        sharing_config = _resolve_config(raw_config)
    except ValueError as exc:
        logger.warning("[%s] Config parse error: %s", request_id, exc)
        return jsonify({"error": f"Could not parse config JSON: {exc}"}), 400

    # ---- Validate the upload ----------------------------------------------
    if "file" not in request.files:
        return jsonify({"error": "No CSV uploaded. Use the 'file' form field."}), 400

    upload = request.files["file"]
    if not upload or upload.filename == "":
        return jsonify({"error": "No file selected."}), 400

    filename = secure_filename(upload.filename or "")
    if not filename.lower().endswith(".csv"):
        return jsonify({"error": "File must be a .csv"}), 400

    # ---- Parse the CSV -----------------------------------------------------
    try:
        raw = upload.read()
        domains = parse_domains_from_csv(raw)
    except ValueError as exc:
        logger.warning("[%s] CSV parse error: %s", request_id, exc)
        return jsonify({"error": f"Could not parse CSV: {exc}"}), 400

    if not domains:
        return jsonify({"error": "No domains found in the CSV."}), 400

    if len(domains) > settings.MAX_DOMAINS_PER_REQUEST:
        return jsonify({
            "error": f"Too many domains. Max per request is "
                     f"{settings.MAX_DOMAINS_PER_REQUEST}, got {len(domains)}."
        }), 400

    # NOTE: only log the count and the (non-sensitive) applicationId.
    # NEVER log the secret or the full config.
    logger.info(
        "[%s] Parsed %d domains; applicationId=%s, flow=%s",
        request_id, len(domains), application_id, flow,
    )

    # ---- Run the Entri flow ------------------------------------------------
    client = EntriClient(
        application_id=application_id,
        secret=secret,
        base_url=settings.ENTRI_BASE_URL,
        request_timeout=settings.HTTP_TIMEOUT,
    )

    try:
        client.authenticate()
    except EntriError as exc:
        logger.error("[%s] Auth failed: %s", request_id, exc)
        return jsonify({
            "error": f"Failed to authenticate with Entri. "
                     f"Check applicationId and secret. Details: {exc}"
        }), 502

    try:
        xlsx_bytes = process_domains_to_xlsx(
            client=client,
            domains=domains,
            sharing_flow=flow,
            base_config=sharing_config,
        )
    except Exception as exc:  # noqa: BLE001 - surface unknown errors to operator logs
        logger.exception("[%s] Processing failed", request_id)
        return jsonify({"error": f"Processing failed: {exc}"}), 500

    logger.info("[%s] Completed; returning XLSX (%d bytes)", request_id, len(xlsx_bytes))

    return send_file(
        io.BytesIO(xlsx_bytes),
        as_attachment=True,
        download_name=f"entri-sharing-links_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.xlsx",
        mimetype=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
    )


@app.errorhandler(413)
def too_large(_e):
    return jsonify({
        "error": f"Upload too large. Max CSV size is "
                 f"{settings.MAX_UPLOAD_BYTES // 1024} KB."
    }), 413


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=settings.FLASK_DEBUG)
