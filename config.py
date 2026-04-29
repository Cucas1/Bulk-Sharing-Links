"""
Configuration loaded from environment variables.

Credentials supplied here are OPTIONAL DEFAULTS. The frontend now lets each
user paste their own applicationId, secret, and config JSON, so a public
multi-tenant deploy doesn't need any env vars at all.

Env-var defaults are still honored for backward compatibility: if a form
field arrives empty, we fall back to the env var of the same name.
"""

import os
import json
from dataclasses import dataclass
from typing import Any, Dict

# Load .env file if present (no-op in production where vars are set elsewhere)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# =============================================================================
# Default Sharing Link config object
# =============================================================================
# Pre-fills the JSON textarea on the frontend so non-technical users have a
# working starting point. Users can edit it freely before submitting.
# `prefilledDomain` is always overwritten per-row at request time.
#
# Reference: https://developers.entri.com/api-reference#entrishowentriconfig
# =============================================================================
DEFAULT_SHARING_CONFIG: Dict[str, Any] = {
    "prefilledDomain": "will-be-replaced-per-row.com",
    "dnsRecords": [
        {
            "type": "CNAME",
            "host": "www",
            "value": "your-app.com",
            "ttl": 300,
        },
    ],
}

# Pretty JSON string used as the textarea's initial value.
DEFAULT_SHARING_CONFIG_JSON: str = json.dumps(DEFAULT_SHARING_CONFIG, indent=2)


@dataclass(frozen=True)
class Settings:
    # --- Optional default credentials (used only if form fields are empty) --
    ENTRI_APPLICATION_ID: str = os.environ.get("ENTRI_APPLICATION_ID", "")
    ENTRI_SECRET: str = os.environ.get("ENTRI_SECRET", "")

    # --- Entri API ----------------------------------------------------------
    ENTRI_BASE_URL: str = os.environ.get("ENTRI_BASE_URL", "https://api.goentri.com")

    # Default sharing flow when form doesn't specify one.
    ENTRI_SHARING_FLOW: str = os.environ.get("ENTRI_SHARING_FLOW", "connect")

    # --- Limits & timeouts --------------------------------------------------
    HTTP_TIMEOUT: float = float(os.environ.get("HTTP_TIMEOUT", "30"))
    MAX_DOMAINS_PER_REQUEST: int = int(os.environ.get("MAX_DOMAINS_PER_REQUEST", "1000"))
    MAX_UPLOAD_BYTES: int = int(os.environ.get("MAX_UPLOAD_BYTES", str(2 * 1024 * 1024)))  # 2 MB

    # Cap on the JSON config textarea size to avoid abuse.
    MAX_CONFIG_BYTES: int = int(os.environ.get("MAX_CONFIG_BYTES", str(64 * 1024)))  # 64 KB

    # --- Flask --------------------------------------------------------------
    FLASK_DEBUG: bool = os.environ.get("FLASK_DEBUG", "false").lower() == "true"


settings = Settings()
