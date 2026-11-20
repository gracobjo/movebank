from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from movebank.infrastructure.http.response import HttpResponse


class HttpClientError(Exception):
    """Base class for errors raised by the generic HTTP client."""


class HttpConnectionError(HttpClientError):
    """A connection to the HTTP server could not be established."""

    def __init__(self, method: str, url: str) -> None:
        self.method = method
        self.url = url
        super().__init__(f"Connection failed during HTTP {method}.")


class HttpTimeoutError(HttpClientError):
    """An HTTP request exceeded its configured timeout."""

    def __init__(self, method: str, url: str) -> None:
        self.method = method
        self.url = url
        super().__init__(f"HTTP {method} request timed out.")


class HttpRequestError(HttpClientError):
    """An HTTP transport error other than a connection failure or timeout."""

    def __init__(self, method: str, url: str) -> None:
        self.method = method
        self.url = url
        super().__init__(f"HTTP {method} request failed.")


class HttpStatusError(HttpClientError):
    """The server returned an unsuccessful HTTP status code."""

    def __init__(self, response: HttpResponse) -> None:
        self.response = response
        super().__init__(f"HTTP {response.method} returned status {response.status_code}.")


class ResponseParsingError(HttpClientError):
    """The response body could not be interpreted as the requested format."""

    def __init__(self, response: HttpResponse) -> None:
        self.response = response
        super().__init__(f"HTTP {response.status_code} response body is not valid JSON.")
