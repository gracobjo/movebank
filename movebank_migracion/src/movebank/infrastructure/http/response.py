import json
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from movebank.infrastructure.http.exceptions import ResponseParsingError


@dataclass(frozen=True)
class HttpResponse:
    """A transport-independent snapshot of an HTTP response."""

    method: str
    url: str
    status_code: int
    headers: Mapping[str, str]
    elapsed_ms: float
    content_type: str | None
    text: str
    content: bytes

    def __post_init__(self) -> None:
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))

    def json(self) -> Any:
        """Decode a JSON response body or raise ResponseParsingError."""
        try:
            return json.loads(self.text)
        except json.JSONDecodeError as exc:
            raise ResponseParsingError(self) from exc
