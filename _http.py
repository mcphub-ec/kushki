"""Kushki HTTP client module — dual-key auth, raises RuntimeError on errors."""

from __future__ import annotations

import json
from typing import Any

import httpx

from config import BASE_URL, HTTP_TIMEOUT, logger


def _build_headers(auth_type: str = "private") -> dict[str, str]:
    import os
    resolved_public = os.getenv("KUSHKI_PUBLIC_KEY", "")
    resolved_private = os.getenv("KUSHKI_PRIVATE_KEY", "")
    if not resolved_public or not resolved_private:
        raise RuntimeError("Both KUSHKI_PUBLIC_KEY and KUSHKI_PRIVATE_KEY env vars are required.")
    headers = {"Content-Type": "application/json"}
    if auth_type == "public":
        headers["Public-Merchant-Id"] = resolved_public
    else:
        headers["Private-Merchant-Id"] = resolved_private
    return headers


async def _kushki_request(method: str, path: str, *, auth_type: str = "private", json_body: dict | None = None) -> dict:
    """Execute a Kushki API request. Raises RuntimeError on any failure."""
    url = f"{BASE_URL}{path}"
    logger.info("→ %s %s [%s key]", method.upper(), url, auth_type)
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            headers = _build_headers(auth_type)
            if method.upper() in ["GET", "DELETE"] and not json_body:
                response = await client.request(method, url, headers=headers)
            else:
                response = await client.request(method, url, headers=headers, json=json_body)
    except httpx.ConnectError as exc:
        raise RuntimeError(f"Cannot connect to Kushki API ({url}). Detail: {exc}") from exc
    except httpx.TimeoutException as exc:
        raise RuntimeError(f"Timeout connecting to Kushki API ({url}). Detail: {exc}") from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Unexpected HTTP error contacting Kushki API: {exc}") from exc

    if response.status_code >= 400:
        try:
            error_body = response.json()
        except Exception:
            error_body = response.text
        status = response.status_code
        detail = (
            f"Error in Kushki ({status}) calling {path}. "
            f"Response: {json.dumps(error_body, ensure_ascii=False) if isinstance(error_body, dict) else error_body}"
        )
        logger.error("← %s %s → %d: %s", method.upper(), url, status, detail)
        raise RuntimeError(detail)

    try:
        data = response.json()
    except Exception:
        data = {"status_code": response.status_code, "text": response.text}
    logger.info("← %s %s → %d OK", method.upper(), url, response.status_code)
    return data
