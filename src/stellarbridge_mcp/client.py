"""HTTP client for the Stellarbridge API using X-API-Key on every request."""

from __future__ import annotations

import threading
from typing import Any

import httpx

from .config import settings


def _unwrap_api_response_data(raw: Any) -> Any:
    """Return inner ``data`` from Stellarbridge ``{data, error}`` JSON when present."""
    if not isinstance(raw, dict) or "data" not in raw:
        return raw
    if raw.get("error") is not None:
        return raw
    return raw["data"]


class StellarBridgeClient:
    """Thin async HTTP client for the Stellarbridge REST API.

    Sends X-API-Key on every request. A single shared instance is used
    across all MCP tool invocations within a server process.
    """

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _base(self) -> str:
        return settings.api_url.rstrip("/") + "/api/v1"

    def _headers(self, *, form_body: bool = False) -> dict[str, str]:
        """Attach auth. Stellarbridge uses ``X-API-Key`` only; not ``Authorization: Bearer``."""
        headers: dict[str, str] = {}
        if not form_body:
            headers["Content-Type"] = "application/json"
        api_key = settings.api_key
        if api_key:
            headers["X-API-Key"] = api_key
        return headers

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
        data: dict[str, str] | None = None,
    ) -> Any:
        """Make a request with X-API-Key header."""
        if json is not None and data is not None:
            raise ValueError("cannot pass both json and data")
        api_key = settings.api_key
        if not api_key:
            raise RuntimeError(
                "No API key configured. Set STELLARBRIDGE_API_KEY environment variable."
            )
        url = f"{self._base()}{path}"
        with httpx.Client(timeout=settings.http_timeout) as client:
            resp = client.request(
                method,
                url,
                headers=self._headers(form_body=data is not None),
                params={k: v for k, v in (params or {}).items() if v is not None},
                json=json,
                data=data,
            )
            resp.raise_for_status()
            if resp.content:
                return resp.json()
            return None

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
        raw = self._request("DELETE", f"/objects/{object_id}")
        return _unwrap_api_response_data(raw)

    def get_upload_url(self, object_id: int) -> Any:
        return self._request("GET", f"/objects/{object_id}/upload-url")

    def complete_upload(self, object_id: int, bucket: str, etag: str, size_bytes: int) -> Any:
        return self._request(
            "POST",
            f"/objects/{object_id}/upload/complete",
            json={"bucket": bucket, "etag": etag, "size_bytes": size_bytes},
        )

    def get_download_url(self, object_id: int) -> Any:
        return self._request("GET", f"/objects/{object_id}/download-url")

    def share_object(self, object_id: int, recipient_email: str) -> Any:
        return self._request(
            "POST", f"/objects/{object_id}/share", json={"recipient_email": recipient_email}
        )

    # ------------------------------------------------------------------
    # Drive – policy attachments
    # ------------------------------------------------------------------

    def list_policy_attachments(self, object_id: int) -> Any:
        return self._request("GET", f"/objects/{object_id}/policy-attachments")

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------

    def list_projects(self) -> Any:
        return self._request("GET", "/projects")

    def get_project(self, project_id: int) -> Any:
        return self._request("GET", f"/projects/{project_id}")

    def create_project(self, name: str, partner_ids: list[int]) -> Any:
        # Matches tenancy.createProjectOrgBody: `json:"partner_ids"`.
        return self._request("POST", "/projects", json={"name": name, "partner_ids": partner_ids})

    def delete_project(self, project_id: int) -> Any:
        raw = self._request("DELETE", f"/projects/{project_id}")
        return _unwrap_api_response_data(raw)

    # ------------------------------------------------------------------
    # Transfers (bridge)
    # ------------------------------------------------------------------

    def list_transfers(self, org_id: str | None = None) -> Any:
        return self._request("GET", "/transfers", params={"orgId": org_id})

    def get_transfer(self, transfer_id: str) -> Any:
        return self._request("GET", f"/transfers/{transfer_id}")

    def delete_transfer(self, transfer_id: str) -> Any:
        return self._request("DELETE", f"/transfers/{transfer_id}")

    def share_transfer(self, transfer_id: str, recipient_email: str) -> Any:
        return self._request(
            "POST",
            f"/bridge/transfers/{transfer_id}/share",
            json={"recipient_email": recipient_email},
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
        """GET /public/download/info/:tid — lives under /api/v1 with the same auth as other routes."""
        raw = self._request("GET", f"/public/download/info/{transfer_id}")
        return _unwrap_api_response_data(raw)

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
        """Create a file request.

        The live API expects ``application/x-www-form-urlencoded`` with
        ``email_invite=true`` and ``uploader`` (recipient), not JSON (see
        ``TransferRequestCreateHandler`` in stellarbridge-app).
        """
        recipient = str(payload.get("recipientEmail", "")).strip()
        form: dict[str, str] = {
            "email_invite": "true",
            "uploader": recipient,
        }
        title = payload.get("title")
        message = payload.get("message")
        instruction_parts: list[str] = []
        if title:
            instruction_parts.append(str(title))
        if message:
            instruction_parts.append(str(message))
        if instruction_parts:
            form["instruction"] = "\n\n".join(instruction_parts)
        raw = self._request("POST", "/bridge/transfer/request/create", data=form)
        return _unwrap_api_response_data(raw)

    def get_file_request(self, request_id: str) -> Any:
        return self._request("GET", f"/bridge/transfer/request/get/{request_id}")

    def delete_file_request(self, request_id: str) -> Any:
        return self._request("DELETE", f"/bridge/transfer/request/delete/{request_id}")

    # ------------------------------------------------------------------
    # Audit logs
    # ------------------------------------------------------------------

    def get_audit_logs(self, **filters: Any) -> Any:
        result = self._request("GET", "/logs", params=filters)
        # Some deployments return 2xx with an empty body when there are no rows;
        # _request maps that to None. Audit logs are always a JSON array.
        if result is None:
            return []
        return result


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
