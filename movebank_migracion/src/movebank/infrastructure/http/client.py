import logging
import time
from collections.abc import Mapping
from typing import Any, Self

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from movebank.infrastructure.http.exceptions import (
    HttpConnectionError,
    HttpRequestError,
    HttpStatusError,
    HttpTimeoutError,
)
from movebank.infrastructure.http.response import HttpResponse

logger = logging.getLogger(__name__)

Timeout = float | tuple[float, float]
RequestData = Mapping[str, Any] | str | bytes | None


class HttpClient:
    """Send HTTP requests through a reusable requests.Session."""

    def __init__(
        self,
        timeout: Timeout = 10.0,
        session: requests.Session | None = None,
    ) -> None:
        self.timeout = timeout
        if session is None:
            self.session = requests.Session()
            retries = Retry(
                total=3,
                connect=0,
                read=0,
                other=0,
                status=3,
                backoff_factor=1,
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods=frozenset({"GET"}),
                raise_on_status=False,
                respect_retry_after_header=True,
            )
            adapter = HTTPAdapter(max_retries=retries)
            self.session.mount("http://", adapter)
            self.session.mount("https://", adapter)
        else:
            self.session = session

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        json: Any = None,
        data: RequestData = None,
        timeout: Timeout | None = None,
    ) -> HttpResponse:
        """Send one request and return its response metadata and body."""
        method = method.strip().upper()
        if not method:
            raise ValueError("HTTP method cannot be empty.")

        started = time.perf_counter()
        try:
            response = self.session.request(
                method,
                url,
                params=params,
                headers=headers,
                json=json,
                data=data,
                timeout=self.timeout if timeout is None else timeout,
            )
        except requests.Timeout as exc:
            logger.warning("HTTP %s request timed out.", method)
            raise HttpTimeoutError(method, url) from exc
        except requests.ConnectionError as exc:
            logger.warning("HTTP %s connection failed.", method)
            raise HttpConnectionError(method, url) from exc
        except requests.RequestException as exc:
            logger.warning("HTTP %s request failed.", method)
            raise HttpRequestError(method, url) from exc

        elapsed_ms = (time.perf_counter() - started) * 1000
        result = HttpResponse(
            method=method,
            url=response.url or url,
            status_code=response.status_code,
            headers=dict(response.headers),
            elapsed_ms=elapsed_ms,
            content_type=response.headers.get("Content-Type"),
            text=response.text,
            content=response.content,
        )
        logger.info(
            "HTTP %s returned status %d in %.2f ms.",
            result.method,
            result.status_code,
            result.elapsed_ms,
        )
        if result.status_code >= 400:
            logger.warning("HTTP %s returned an unsuccessful status.", result.method)
            raise HttpStatusError(result)
        return result

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: Timeout | None = None,
    ) -> HttpResponse:
        return self.request("GET", url, params=params, headers=headers, timeout=timeout)

    def post(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        json: Any = None,
        data: RequestData = None,
        timeout: Timeout | None = None,
    ) -> HttpResponse:
        return self.request(
            "POST",
            url,
            params=params,
            headers=headers,
            json=json,
            data=data,
            timeout=timeout,
        )

    def put(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        json: Any = None,
        data: RequestData = None,
        timeout: Timeout | None = None,
    ) -> HttpResponse:
        return self.request(
            "PUT",
            url,
            params=params,
            headers=headers,
            json=json,
            data=data,
            timeout=timeout,
        )

    def patch(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        json: Any = None,
        data: RequestData = None,
        timeout: Timeout | None = None,
    ) -> HttpResponse:
        return self.request(
            "PATCH",
            url,
            params=params,
            headers=headers,
            json=json,
            data=data,
            timeout=timeout,
        )

    def delete(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        json: Any = None,
        data: RequestData = None,
        timeout: Timeout | None = None,
    ) -> HttpResponse:
        return self.request(
            "DELETE",
            url,
            params=params,
            headers=headers,
            json=json,
            data=data,
            timeout=timeout,
        )

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self.session.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
