# clients/sharepoint_client.py

import asyncio
import os
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

import aiohttp
import msal
from dotenv import load_dotenv

from utils.logging_setup import logger

# Load auth variables directly in this module for self-containment
load_dotenv()
TENANT_ID = os.getenv("TENANT_ID")
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")


class SharePointClient:
    # Class-level cache and lock to ensure all instances share a single token
    _token_cache: Dict[str, Any] = {}
    _token_lock = asyncio.Lock()

    # Class-level performance tracking for the shared token
    _token_acquisitions = 0
    _token_cache_hits = 0

    def __init__(
        self,
        site_id: str,
        drive_id: str,
        max_connections: int,
        max_retries: int,
        retry_delay: float,
    ):
        if not all([TENANT_ID, CLIENT_ID, CLIENT_SECRET]):
            raise ValueError(
                "Authentication environment variables (TENANT_ID, CLIENT_ID, CLIENT_SECRET) are not set."
            )

        self.site_id = site_id
        self.drive_id = drive_id
        self.session: Optional[aiohttp.ClientSession] = None

        # Initialize instance-level stats and resilience settings
        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        self.connection_semaphore = asyncio.Semaphore(max_connections)
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        # Each client instance will have its own MSAL app object
        self.app = msal.ConfidentialClientApplication(
            CLIENT_ID,
            authority=f"https://login.microsoftonline.com/{TENANT_ID}",
            client_credential=CLIENT_SECRET,
        )

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def _get_token(self) -> Optional[str]:
        """Internal async-safe token management using a shared class-level cache."""
        # This check is non-blocking and safe to do outside the lock
        if (
            "access_token" in SharePointClient._token_cache
            and SharePointClient._token_cache.get("expires_in", 0) > 300
        ):
            SharePointClient._token_cache_hits += 1
            return SharePointClient._token_cache["access_token"]

        async with self._token_lock:
            # Re-check the cache inside the lock in case another coroutine just refreshed it
            if (
                "access_token" in SharePointClient._token_cache
                and SharePointClient._token_cache.get("expires_in", 0) > 300
            ):
                SharePointClient._token_cache_hits += 1
                return SharePointClient._token_cache["access_token"]

            logger.info("Token expired or not in cache, acquiring a new one.")
            result = self.app.acquire_token_for_client(
                scopes=["https://graph.microsoft.com/.default"]
            )

            if "access_token" in result:
                SharePointClient._token_cache = result
                SharePointClient._token_acquisitions += 1
                logger.info(
                    f"New token acquired. Expires in {result.get('expires_in')} seconds."
                )
                return result["access_token"]

            logger.error(f"Failed to acquire token: {result.get('error_description')}")
            return None

    async def _get_auth_headers(self) -> Optional[Dict[str, str]]:
        token = await self._get_token()
        if not token:
            return None
        return {"Authorization": f"Bearer {token}"}

    async def make_request(
        self, method: str, endpoint: str, **kwargs
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        if not self.session:
            logger.error("Client session not initialized. Use an 'async with' block.")
            return None, None
        self.total_requests += 1
        relative_endpoint = (
            urlparse(endpoint).path if endpoint.startswith("https://") else endpoint
        )
        full_url = f"https://graph.microsoft.com/v1.0{relative_endpoint}"
        for attempt in range(self.max_retries):
            async with self.connection_semaphore:
                try:
                    headers = await self._get_auth_headers()
                    if not headers:
                        await asyncio.sleep(self.retry_delay)
                        continue
                    headers.update(
                        kwargs.pop("headers", {"Accept": "application/json"})
                    )
                    async with self.session.request(
                        method, full_url, headers=headers, **kwargs
                    ) as response:
                        if response.status in [200, 201, 202, 204]:
                            self.successful_requests += 1
                            response_body = {}
                            if "application/json" in response.content_type:
                                response_body = await response.json()
                            return response_body, dict(response.headers)
                        if response.status == 429:
                            retry_after = int(
                                response.headers.get(
                                    "Retry-After", self.retry_delay * (2**attempt)
                                )
                            )
                            logger.warning(
                                f"Rate limited (429). Retrying after {retry_after} seconds."
                            )
                            await asyncio.sleep(retry_after)
                            continue
                        error_text = await response.text()
                        logger.error(
                            f"Request failed: {method} {full_url} | Status: {response.status} | Response: {error_text[:500]} (Attempt {attempt + 1}/{self.max_retries})"
                        )
                        if response.status in [400, 401, 403, 404]:
                            logger.error(
                                "Fatal error encountered. Stopping retries for this request."
                            )
                            break
                        await asyncio.sleep(self.retry_delay * (2**attempt))
                except aiohttp.ClientError as e:
                    logger.error(
                        f"A client error occurred: {e} (Attempt {attempt + 1}/{self.max_retries})",
                        exc_info=True,
                    )
                    await asyncio.sleep(self.retry_delay * (2**attempt))
        self.failed_requests += 1
        logger.error(f"All {self.max_retries} attempts failed for {method} {full_url}")
        return None, None

    async def find_folder_by_path(self, path: str) -> Optional[Dict]:
        if not path:
            response, _ = await self.make_request(
                "GET", f"/drives/{self.drive_id}/root"
            )
            return response
        current_item_id = "root"
        for part in path.split("/"):
            if not part:
                continue
            endpoint = f"/drives/{self.drive_id}/items/{current_item_id}/children?$filter=name eq '{part}'"
            response, _ = await self.make_request("GET", endpoint)
            if not response or not response.get("value"):
                logger.error(
                    f"Could not find path part '{part}' in folder with ID '{current_item_id}'."
                )
                return None
            found_folder = next(
                (item for item in response["value"] if "folder" in item), None
            )
            if not found_folder:
                logger.error(f"Path part '{part}' exists but is not a folder.")
                return None
            current_item_id = found_folder["id"]
        final_folder, _ = await self.make_request(
            "GET", f"/drives/{self.drive_id}/items/{current_item_id}"
        )
        return final_folder

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    def get_request_stats(self) -> dict:
        return {
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
        }

    @staticmethod
    def get_token_stats() -> dict:
        """Class method to get stats from the shared cache."""
        return {
            "token_acquisitions": SharePointClient._token_acquisitions,
            "token_cache_hits": SharePointClient._token_cache_hits,
        }
