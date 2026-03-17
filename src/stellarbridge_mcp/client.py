"""HTTP client for the Stellarbridge API with automatic JWT authentication."""

from __future__ import annotations

import threading
from typing import Any

import httpx

from .config import settings


class StellarBridgeClient:
    """Thin async HTTP client for the Stellarbridge REST API.

    Handles JWT acquisition (via API key exchange) and token refresh
    transparently.  A single shared instance is used across all MCP tool
    invocations within a server process.
    """

    def __init__(self) -> None:
        self._token: str = settings.stellarbridge_jwt_token
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _base(self) -> str:
        return settings.stellarbridge_api_url.rstrip("/") + "/api/v1"

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _authenticate(self) -> None:
        """Exchange API key for JWT token (synchronous, called lazily)."""
        api_key = settings.stellarbridge_api_key
        if not api_key:
            raise RuntimeError(
                "No API key configured. Set STELLARBRIDGE_API_KEY environment variable."
            )
        url = self._base().replace("/api/v1", "") + "/api/v1/auth"
        with httpx.Client(timeout=settings.http_timeout) as client:
            resp = client.post(url, json={"apiKey": api_key})
            resp.raise_for_status()
            data = resp.json()
            self._token = data["token"]

    def _ensure_token(self) -> None:
        if not self._token:
            with self._lock:
                if not self._token:
                    self._authenticate()

    # ------------------------------------------------------------------
    # Low-level request helpers
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        retry: bool = True,
    ) -> Any:
        """Make an authenticated request, retrying once on 401."""
        self._ensure_token()
        url = f"{self._base()}{path}"
        with httpx.Client(timeout=settings.http_timeout) as client:
            resp = client.request(
                method,
                url,
                headers=self._headers(),
                params={k: v for k, v in (params or {}).items() if v is not None},
                json=json,
            )
            if resp.status_code == 401 and retry:
                # Token may have expired – re-authenticate once
                self._token = ""
                self._authenticate()
                return self._request(method, path, params=params, json=json, retry=False)
            resp.raise_for_status()
            if resp.content:
                return resp.json()
            return None

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def authenticate(self, api_key: str) -> str:
        """Explicitly authenticate with the given API key, return JWT."""
        url = f"{self._base()}/auth"
        with httpx.Client(timeout=settings.http_timeout) as client:
            resp = client.post(url, json={"apiKey": api_key})
            resp.raise_for_status()
            data = resp.json()
            self._token = data["token"]
            return self._token

    # ------------------------------------------------------------------
    # Drive / VFS – objects
    # ------------------------------------------------------------------

    def list_objects(self, project_id: int, parent_id: int | None = None) -> Any:
        return self._request(
            "GET", "/objects", params={"project_id": project_id, "parent_id": parent_id}
        )

    def get_object(self, object_id: int) -> Any:
        return self._request("GET", f"/objects/{object_id}")

    def create_object(self, payload: dict[str, Any]) -> Any:
        return self._request("POST", "/objects", json=payload)

    def update_object(self, object_id: int, payload: dict[str, Any]) -> Any:
        return self._request("PATCH", f"/objects/{object_id}", json=payload)

    def delete_object(self, object_id: int) -> Any:
        return self._request("DELETE", f"/objects/{object_id}")

    def get_upload_url(self, object_id: int) -> Any:
        return self._request("GET", f"/objects/{object_id}/upload-url")

    def complete_upload(self, object_id: int) -> Any:
        return self._request("POST", f"/objects/{object_id}/upload/complete")

    def get_download_url(self, object_id: int) -> Any:
        return self._request("GET", f"/objects/{object_id}/download-url")

    def share_object(self, object_id: int, recipient_email: str) -> Any:
        return self._request(
            "POST", f"/objects/{object_id}/share", json={"recipientEmail": recipient_email}
        )

    # ------------------------------------------------------------------
    # Drive – policy attachments
    # ------------------------------------------------------------------

    def list_policy_attachments(self, object_id: int) -> Any:
        return self._request("GET", f"/objects/{object_id}/policy-attachments")

    def attach_policy(self, object_id: int, policy_id: str) -> Any:
        return self._request(
            "POST", f"/objects/{object_id}/policy-attachments", json={"policyId": policy_id}
        )

    def detach_policy(self, object_id: int, attachment_id: str) -> Any:
        return self._request("DELETE", f"/objects/{object_id}/policy-attachments/{attachment_id}")

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------

    def list_projects(self) -> Any:
        return self._request("GET", "/projects")

    def get_project(self, project_id: int) -> Any:
        return self._request("GET", f"/projects/{project_id}")

    def create_project(self, name: str, partner_ids: list[int]) -> Any:
        return self._request("POST", "/projects", json={"name": name, "partnerIds": partner_ids})

    def delete_project(self, project_id: int) -> Any:
        return self._request("DELETE", f"/projects/{project_id}")

    # ------------------------------------------------------------------
    # Transfers (bridge)
    # ------------------------------------------------------------------

    def list_transfers(self, org_id: str | None = None) -> Any:
        return self._request("GET", "/transfers", params={"orgId": org_id})

    def get_transfer(self, transfer_id: str) -> Any:
        return self._request("GET", f"/transfers/{transfer_id}")

    def delete_transfer(self, transfer_id: str) -> Any:
        return self._request("DELETE", f"/bridge/download/delete-transfer/{transfer_id}")

    def share_transfer(self, transfer_id: str, recipient_email: str) -> Any:
        return self._request(
            "POST",
            f"/bridge/transfers/{transfer_id}/share",
            json={"recipientEmail": recipient_email},
        )

    def add_transfer_to_drive(
        self, transfer_id: str, project_id: int, parent_id: int | None = None
    ) -> Any:
        payload: dict[str, Any] = {"projectId": project_id}
        if parent_id is not None:
            payload["parentId"] = parent_id
        return self._request(
            "POST", f"/bridge/transfers/{transfer_id}/add-to-drive", json=payload
        )

    def get_transfer_public_info(self, transfer_id: str) -> Any:
        """Public endpoint – no auth required."""
        url = f"{self._base()}/public/download/info/{transfer_id}"
        with httpx.Client(timeout=settings.http_timeout) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.json()

    def initialize_multipart_upload(self, payload: dict[str, Any]) -> Any:
        return self._request(
            "POST", "/bridge/uploads/initialize-multipart-upload", json=payload
        )

    def get_multipart_presigned_urls(self, payload: dict[str, Any]) -> Any:
        return self._request(
            "POST", "/bridge/uploads/get-multipart-presigned-urls", json=payload
        )

    def finalize_multipart_upload(self, payload: dict[str, Any]) -> Any:
        return self._request(
            "POST", "/bridge/uploads/finalize-multipart-upload", json=payload
        )

    def cancel_multipart_upload(self, payload: dict[str, Any]) -> Any:
        return self._request("POST", "/bridge/uploads/cancel", json=payload)

    # ------------------------------------------------------------------
    # File requests
    # ------------------------------------------------------------------

    def create_file_request(self, payload: dict[str, Any]) -> Any:
        return self._request("POST", "/bridge/transfer/request/create", json=payload)

    def get_file_request(self, request_id: str) -> Any:
        return self._request("GET", f"/bridge/transfer/request/get/{request_id}")

    def delete_file_request(self, request_id: str) -> Any:
        return self._request("DELETE", f"/bridge/transfer/request/delete/{request_id}")

    # ------------------------------------------------------------------
    # Audit logs
    # ------------------------------------------------------------------

    def get_audit_logs(self, **filters: Any) -> Any:
        return self._request("GET", "/logs", params=filters)


# Module-level singleton
_client: StellarBridgeClient | None = None
_client_lock = threading.Lock()


def get_client() -> StellarBridgeClient:
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = StellarBridgeClient()
    return _client
