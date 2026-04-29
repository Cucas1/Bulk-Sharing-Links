"""
Thin client for the Entri API.

Handles two endpoints:
  1. POST /token              -> JWT token
     https://developers.entri.com/getting-started#3-get-a-jwt-token
  2. POST /sharing/{flow}     -> sharing link for a single config
     https://developers.entri.com/api-reference#sharing-links-api

The JWT lives 60 minutes, so we cache it and reuse it across all domains in
a batch. We refresh on 401s.
"""

import logging
import time
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

# Conservative buffer: refresh the token a bit before its 60-minute expiry.
TOKEN_LIFETIME_SECONDS = 55 * 60


class EntriError(Exception):
    """Raised when an Entri API call fails."""


class EntriClient:
    def __init__(
        self,
        application_id: str,
        secret: str,
        base_url: str = "https://api.goentri.com",
        request_timeout: float = 30.0,
    ):
        if not application_id or not secret:
            raise ValueError("application_id and secret are required")

        self.application_id = application_id
        self._secret = secret
        self.base_url = base_url.rstrip("/")
        self.timeout = request_timeout

        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0

        self._session = requests.Session()

    # ------------------------------------------------------------------ auth
    def authenticate(self) -> str:
        """Fetch a fresh JWT and cache it. Returns the token."""
        url = f"{self.base_url}/token"
        payload = {"applicationId": self.application_id, "secret": self._secret}

        try:
            resp = self._session.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise EntriError(f"Network error contacting {url}: {exc}") from exc

        if not resp.ok:
            raise EntriError(
                f"Token request failed ({resp.status_code}): {resp.text[:300]}"
            )

        try:
            data = resp.json()
        except ValueError as exc:
            raise EntriError(f"Token response was not JSON: {resp.text[:300]}") from exc

        token = data.get("auth_token")
        if not token:
            raise EntriError(
                f"Token response missing 'auth_token' field. Body: {data}"
            )

        self._token = token
        self._token_expires_at = time.time() + TOKEN_LIFETIME_SECONDS
        logger.info("Obtained new Entri JWT (cached %d minutes)", TOKEN_LIFETIME_SECONDS // 60)
        return token

    def _ensure_token(self) -> str:
        if self._token and time.time() < self._token_expires_at:
            return self._token
        return self.authenticate()

    # -------------------------------------------------------- sharing links
    def create_sharing_link(
        self,
        config: Dict[str, Any],
        flow: str = "connect",
    ) -> Dict[str, Any]:
        """
        Create a sharing link for the given config.

        Returns the parsed JSON response, which contains `link` and `job_id`.
        Raises EntriError on failure.
        """
        if flow not in ("connect", "sell"):
            raise ValueError(f"flow must be 'connect' or 'sell', got {flow!r}")

        token = self._ensure_token()
        url = f"{self.base_url}/sharing/{flow}"
        body = {
            "applicationId": self.application_id,
            "config": config,
        }
        headers = {
            "Authorization": token,
            "applicationId": self.application_id,
            "Content-Type": "application/json",
        }

        try:
            resp = self._session.post(url, json=body, headers=headers, timeout=self.timeout)
        except requests.RequestException as exc:
            raise EntriError(f"Network error contacting {url}: {exc}") from exc

        # Token may have expired early; refresh once and retry.
        if resp.status_code == 401:
            logger.info("Got 401 on /sharing/%s; refreshing token and retrying", flow)
            token = self.authenticate()
            headers["Authorization"] = token
            try:
                resp = self._session.post(url, json=body, headers=headers, timeout=self.timeout)
            except requests.RequestException as exc:
                raise EntriError(f"Network error retrying {url}: {exc}") from exc

        if not resp.ok:
            raise EntriError(
                f"/sharing/{flow} failed ({resp.status_code}): {resp.text[:500]}"
            )

        try:
            data = resp.json()
        except ValueError as exc:
            raise EntriError(
                f"/sharing/{flow} response was not JSON: {resp.text[:300]}"
            ) from exc

        if "link" not in data:
            raise EntriError(f"Response missing 'link' field. Body: {data}")

        return data
