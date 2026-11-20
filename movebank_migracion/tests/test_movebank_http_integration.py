import hashlib
from io import BytesIO
from unittest.mock import Mock

import pytest
import requests
from requests.adapters import HTTPAdapter
from urllib3._collections import HTTPHeaderDict
from urllib3.connectionpool import HTTPConnectionPool
from urllib3.response import HTTPResponse
from urllib3.util.retry import Retry

from movebank.infrastructure.http import HttpStatusError
from movebank.infrastructure.http.exceptions import (
    HttpConnectionError,
    HttpRequestError,
    HttpTimeoutError,
)
from movebank.infrastructure.http.response import HttpResponse
from movebank.infrastructure.movebank.client import (
    URL,
    LicenseRequired,
    MovebankClient,
    MovebankError,
)

STUDY_CSV = b"id,name\n1,Study\n"


def make_response(content: bytes, status: int = 200) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response._content = content
    response.encoding = "utf-8"
    response.url = URL
    response.headers["Content-Type"] = "text/csv"
    return response


def mock_http_statuses(monkeypatch, statuses: list[int]) -> list[tuple[str, str, int]]:
    pending_statuses = iter(statuses)
    calls = []

    def fake_make_request(self, conn, method, url, *args, **kwargs):
        status = next(pending_statuses)
        calls.append((method, url, status))
        body = STUDY_CSV if status < 400 else b"Movebank failure"
        return HTTPResponse(
            body=BytesIO(body),
            headers=HTTPHeaderDict({"Content-Type": "text/csv"}),
            status=status,
            preload_content=kwargs.get("preload_content", False),
            decode_content=kwargs.get("decode_content", False),
        )

    monkeypatch.setattr(HTTPConnectionPool, "_make_request", fake_make_request)
    monkeypatch.setattr(Retry, "sleep", lambda self, response=None: None)
    return calls


@pytest.fixture
def client():
    instance = MovebankClient(interval=0)
    yield instance
    instance.close()


def test_shared_session_basic_auth_adapter_and_single_close(monkeypatch):
    original_mount = requests.Session.mount
    mounts = []

    def record_mount(session, prefix, adapter):
        mounts.append((session, prefix, adapter))
        return original_mount(session, prefix, adapter)

    monkeypatch.setattr(requests.Session, "mount", record_mount)
    client = MovebankClient("test-user", "test-password", interval=0)

    assert client.session.auth == ("test-user", "test-password")
    prepared = client.session.prepare_request(requests.Request("GET", URL))
    assert prepared.headers["Authorization"].startswith("Basic ")
    assert client._http_client.session is client.session

    session_mounts = [
        (prefix, adapter) for session, prefix, adapter in mounts if session is client.session
    ]
    assert [prefix for prefix, _ in session_mounts] == ["https://", "http://", "https://"]
    assert isinstance(session_mounts[-1][1], HTTPAdapter)
    assert client.session.get_adapter(URL) is session_mounts[-1][1]

    close = Mock(wraps=client.session.close)
    client.session.close = close
    client.close()
    close.assert_called_once_with()


def test_get_uses_shared_session_timeout_and_parses_csv(client, monkeypatch):
    calls = []

    def request(method, url, **kwargs):
        calls.append((client.session, method, url, kwargs))
        return make_response(b"\xef\xbb\xbf" + STUDY_CSV)

    monkeypatch.setattr(client.session, "request", request)
    original_get = client._http_client.get
    http_responses = []

    def get(*args, **kwargs):
        response = original_get(*args, **kwargs)
        http_responses.append(response)
        return response

    monkeypatch.setattr(client._http_client, "get", get)
    params = {"entity_type": "study", "study_id": 123}

    rows = client.read(params)

    assert rows == [{"id": "1", "name": "Study"}]
    assert len(calls) == 1
    session, method, url, kwargs = calls[0]
    assert session is client.session
    assert method == "GET"
    assert url == URL
    assert kwargs["params"] == params
    assert kwargs["timeout"] == (15, 120)
    assert len(http_responses) == 1
    assert isinstance(http_responses[0], HttpResponse)
    assert http_responses[0].content == b"\xef\xbb\xbf" + STUDY_CSV


def test_license_approval_uses_original_bytes_and_same_session(client, monkeypatch):
    terms = b"\xef\xbb\xbfLicense Terms: test\x00original bytes"
    digest = hashlib.md5(terms, usedforsecurity=False).hexdigest()
    responses = iter([make_response(terms), make_response(terms), make_response(STUDY_CSV)])
    calls = []

    def request(method, url, **kwargs):
        calls.append((client.session, method, url, kwargs))
        return next(responses)

    monkeypatch.setattr(client.session, "request", request)
    params = {"entity_type": "study"}

    with pytest.raises(LicenseRequired) as required:
        client.read(params)
    assert required.value.content == terms
    assert required.value.md5 == digest

    assert client.read(params, required.value.md5) == [{"id": "1", "name": "Study"}]
    assert len(calls) == 3
    assert all(call[0] is client.session for call in calls)
    assert [call[1] for call in calls] == ["GET", "GET", "GET"]
    assert calls[0][3]["params"] == params
    assert calls[1][3]["params"] == params
    assert calls[2][3]["params"] == {**params, "license-md5": digest}


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500, 503])
def test_http_status_errors_are_translated_with_response(client, monkeypatch, status):
    monkeypatch.setattr(
        client.session,
        "request",
        Mock(return_value=make_response(b"status response", status)),
    )

    with pytest.raises(MovebankError) as error:
        client.read({"entity_type": "study"})

    assert error.value.status_code == status
    assert error.value.response.status_code == status
    assert error.value.response.content == b"status response"
    assert isinstance(error.value.__cause__, HttpStatusError)
    assert error.value.__cause__.response is error.value.response


@pytest.mark.parametrize(
    ("request_error", "http_error"),
    [
        (requests.ConnectTimeout("connect timeout"), HttpTimeoutError),
        (requests.ReadTimeout("read timeout"), HttpTimeoutError),
        (requests.ConnectionError("connection error"), HttpConnectionError),
        (requests.RequestException("other transport error"), HttpRequestError),
    ],
)
def test_transport_errors_are_translated_and_original_cause_is_preserved(
    client, monkeypatch, request_error, http_error
):
    monkeypatch.setattr(client.session, "request", Mock(side_effect=request_error))

    with pytest.raises(MovebankError) as error:
        client.read({"entity_type": "study"})

    assert error.value.status_code is None
    assert error.value.response is None
    assert http_error.__name__ in str(error.value)
    assert isinstance(error.value.__cause__, http_error)
    assert error.value.__cause__.__cause__ is request_error


def test_movebank_retry_policy_and_get_recovery(client, monkeypatch):
    adapter = client.session.get_adapter(URL)
    retries = adapter.max_retries

    assert retries.total == 3
    assert retries.connect is None
    assert retries.read is None
    assert retries.status is None
    assert retries.other is None
    assert retries.backoff_factor == 1
    assert set(retries.status_forcelist) == {429, 500, 502, 503, 504}
    assert retries.allowed_methods == ["GET"]
    assert retries.respect_retry_after_header is True
    assert retries.raise_on_status is False

    calls = mock_http_statuses(monkeypatch, [503, 200])

    assert client.read({"entity_type": "study"}) == [{"id": "1", "name": "Study"}]
    assert [status for _, _, status in calls] == [503, 200]


def test_exhausted_get_retries_return_final_http_response(client, monkeypatch):
    calls = mock_http_statuses(monkeypatch, [503, 503, 503, 503])

    with pytest.raises(MovebankError) as error:
        client.read({"entity_type": "study"})

    assert len(calls) == 4
    assert error.value.status_code == 503
    assert error.value.response.status_code == 503
    assert error.value.response.content == b"Movebank failure"
    assert isinstance(error.value.__cause__, HttpStatusError)


def test_movebank_adapter_does_not_retry_other_methods_on_status(client, monkeypatch):
    calls = mock_http_statuses(monkeypatch, [503, 200])

    with pytest.raises(HttpStatusError):
        client._http_client.post(URL, data={"study_id": 1})

    assert calls == [("POST", "/movebank/service/direct-read", 503)]
