"""Shared UEX Corp API client, handed to every module instead of each
module managing its own HTTP session.
"""
import requests


class UexApiError(Exception):
    """Generic UEX API failure — network error, bad JSON, non-ok status."""


class UexRateLimitError(UexApiError):
    """UEX's own rate limit was hit (status: requests_limit_reached).
    Kept distinct from UexApiError so callers can show a specific,
    actionable message instead of a generic failure.
    """


class UexApiClient:
    def __init__(self, base_url: str, token: str = ""):
        self.base_url = base_url.rstrip("/") + "/"
        self.token = token
        self._session = requests.Session()

    def get(self, endpoint: str, params: dict | None = None) -> list[dict]:
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        url = self.base_url + endpoint.lstrip("/") + "/"
        try:
            resp = self._session.get(url, params=params, headers=headers, timeout=10)
            resp.raise_for_status()
            payload = resp.json()
        except requests.RequestException as exc:
            raise UexApiError(f"UEX API request failed: {exc}") from exc
        except ValueError as exc:
            raise UexApiError(f"UEX API returned invalid JSON: {exc}") from exc

        status = payload.get("status")
        if status == "requests_limit_reached":
            raise UexRateLimitError(
                "UEX rate limit reached — wait a moment, then retry."
            )
        if status != "ok":
            raise UexApiError(f"UEX API error response: {payload}")
        return payload.get("data", [])
