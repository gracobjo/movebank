import logging
from datetime import timedelta
from io import BytesIO
from unittest.mock import Mock

import pytest
import requests
from urllib3._collections import HTTPHeaderDict
from urllib3.connectionpool import HTTPConnectionPool
from urllib3.response import HTTPResponse
from urllib3.util.retry import Retry

from movebank.infrastructure.http import (
    HttpClient,
    HttpConnectionError,
    HttpRequestError,
    HttpStatusError,
    HttpTimeoutError,
    ResponseParsingError,
)

URL = "https://example.test/animals"


def make_response(
    content: bytes = b'{"ok": true}',
    status: int = 200,
    headers: dict[str, str] | None = None,
) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response._content = content
    response.encoding = "utf-8"
    response.url = URL
    response.headers.update(headers or {})
    response.elapsed = timedelta(milliseconds=12)
    return response


def mock_http_responses(monkeypatch, statuses: list[int]) -> list[tuple[str, str, int]]:
    pending_statuses = iter(statuses)
    calls = []

    def fake_make_request(self, conn, method, url, *args, **kwargs):
        status = next(pending_statuses)
        calls.append((method, url, status))
        return HTTPResponse(
            body=BytesIO(b"OK" if status < 400 else b"Unavailable"),
            headers=HTTPHeaderDict({"Content-Type": "text/plain"}),
            status=status,
            preload_content=kwargs.get("preload_content", False),
            decode_content=kwargs.get("decode_content", False),
        )

    monkeypatch.setattr(HTTPConnectionPool, "_make_request", fake_make_request)
    monkeypatch.setattr(Retry, "sleep", lambda self, response=None: None)
    return calls


@pytest.fixture
def client():
    instance = HttpClient()
    yield instance
    instance.close()


@pytest.mark.parametrize(
    ("method", "verb"),
    [
        ("get", "GET"),
        ("post", "POST"),
        ("put", "PUT"),
        ("patch", "PATCH"),
        ("delete", "DELETE"),
    ],
)
def test_http_verbs_call_session_with_correct_method(client, monkeypatch, method, verb):
    calls = []

    def fake_request(request_method, url, **kwargs):
        calls.append((request_method, url, kwargs))
        return make_response()

    monkeypatch.setattr(client.session, "request", fake_request)
    result = getattr(client, method)(URL, headers={"X-Example": "yes"})

    assert result.method == verb
    assert calls[0][0:2] == (verb, URL)
    assert calls[0][2]["headers"] == {"X-Example": "yes"}


def test_generic_request_forwards_query_headers_json_and_timeout(client, monkeypatch):
    calls = []
    monkeypatch.setattr(
        client.session,
        "request",
        lambda method, url, **kwargs: calls.append((method, url, kwargs)) or make_response(),
    )
    payload = {"name": "Owl"}
    headers = {"X-Request-ID": "request-1"}

    client.request(
        "post",
        URL,
        params={"study_id": 12},
        headers=headers,
        json=payload,
        timeout=(2.0, 5.0),
    )

    method, url, kwargs = calls[0]
    assert (method, url) == ("POST", URL)
    assert kwargs["params"] == {"study_id": 12}
    assert kwargs["headers"] == headers
    assert kwargs["json"] == payload
    assert kwargs["timeout"] == (2.0, 5.0)


def test_request_forwards_form_data_and_default_timeout(client, monkeypatch):
    calls = []
    monkeypatch.setattr(
        client.session,
        "request",
        lambda method, url, **kwargs: calls.append(kwargs) or make_response(),
    )
    client.post(URL, data={"name": "Owl"})

    assert calls[0]["data"] == {"name": "Owl"}
    assert calls[0]["timeout"] == 10.0


def test_json_response_can_be_decoded(client, monkeypatch):
    monkeypatch.setattr(
        client.session, "request", lambda *args, **kwargs: make_response(b'{"count": 2}')
    )

    assert client.get(URL).json() == {"count": 2}


def test_text_and_csv_response_are_preserved(client, monkeypatch):
    body = b"name,count\nOwl,2\n"
    monkeypatch.setattr(
        client.session,
        "request",
        lambda *args, **kwargs: make_response(body, headers={"Content-Type": "text/csv"}),
    )

    result = client.get(URL)

    assert result.text == "name,count\nOwl,2\n"
    assert result.content == body
    assert result.content_type == "text/csv"


def test_empty_response_is_preserved(client, monkeypatch):
    monkeypatch.setattr(client.session, "request", lambda *args, **kwargs: make_response(b""))

    result = client.delete(URL)

    assert result.text == ""
    assert result.content == b""


def test_non_json_body_raises_response_parsing_error(client, monkeypatch):
    monkeypatch.setattr(
        client.session, "request", lambda *args, **kwargs: make_response(b"not-json")
    )
    result = client.get(URL)

    with pytest.raises(ResponseParsingError) as error:
        result.json()

    assert error.value.response is result
    assert isinstance(error.value.__cause__, ValueError)


def test_binary_response_content_is_preserved(client, monkeypatch):
    body = b"\x89PNG\r\n\x1a\n"
    monkeypatch.setattr(
        client.session,
        "request",
        lambda *args, **kwargs: make_response(body, headers={"Content-Type": "image/png"}),
    )

    result = client.get(URL)

    assert result.content == body
    assert result.content_type == "image/png"


@pytest.mark.parametrize("status", [404, 500])
def test_http_error_preserves_response(status, client, monkeypatch):
    monkeypatch.setattr(
        client.session, "request", lambda *args, **kwargs: make_response(b"failure", status)
    )

    with pytest.raises(HttpStatusError) as error:
        client.get(URL)

    assert error.value.response.status_code == status
    assert error.value.response.content == b"failure"


def test_timeout_is_translated_and_chained(client, monkeypatch):
    monkeypatch.setattr(
        client.session,
        "request",
        Mock(side_effect=requests.Timeout("sensitive timeout details")),
    )

    with pytest.raises(HttpTimeoutError) as error:
        client.get(URL)

    assert error.value.method == "GET"
    assert error.value.url == URL
    assert isinstance(error.value.__cause__, requests.Timeout)


def test_connection_error_is_translated_and_chained(client, monkeypatch):
    monkeypatch.setattr(
        client.session,
        "request",
        Mock(side_effect=requests.ConnectionError("sensitive connection details")),
    )

    with pytest.raises(HttpConnectionError) as error:
        client.get(URL)

    assert error.value.method == "GET"
    assert error.value.url == URL
    assert isinstance(error.value.__cause__, requests.ConnectionError)


def test_other_request_errors_are_translated_and_chained(client, monkeypatch):
    monkeypatch.setattr(
        client.session,
        "request",
        Mock(side_effect=requests.RequestException("transport failure")),
    )

    with pytest.raises(HttpRequestError) as error:
        client.get(URL)

    assert error.value.method == "GET"
    assert error.value.url == URL
    assert isinstance(error.value.__cause__, requests.RequestException)


def test_empty_method_is_rejected_before_sending(client, monkeypatch):
    send = Mock()
    monkeypatch.setattr(client.session, "request", send)

    with pytest.raises(ValueError, match="cannot be empty"):
        client.request(" ", URL)

    send.assert_not_called()


def test_response_metadata_and_elapsed_time_are_preserved(client, monkeypatch):
    monkeypatch.setattr(
        client.session,
        "request",
        lambda *args, **kwargs: make_response(
            headers={"Content-Type": "application/json", "X-Trace": "trace-1"}
        ),
    )
    ticks = iter([1.0, 1.025])
    monkeypatch.setattr(
        "movebank.infrastructure.http.client.time.perf_counter", lambda: next(ticks)
    )

    result = client.get(URL)

    assert result.method == "GET"
    assert result.url == URL
    assert result.status_code == 200
    assert result.headers["X-Trace"] == "trace-1"
    assert result.content_type == "application/json"
    assert result.elapsed_ms == pytest.approx(25.0)
    assert result.content == b'{"ok": true}'
    assert result.text == '{"ok": true}'
    with pytest.raises(TypeError):
        result.headers["X-Trace"] = "changed"


def test_session_can_be_closed_explicitly():
    session = requests.Session()
    close = Mock(wraps=session.close)
    session.close = close
    client = HttpClient(session=session)

    client.close()

    close.assert_called_once_with()


def test_injected_session_is_reused_without_changing_configuration(monkeypatch):
    session = requests.Session()
    session.auth = ("test-user", "test-password")
    session.headers.update({"X-Session-Header": "preserved"})
    session.cookies.set("session-cookie", "preserved")
    adapters = dict(session.adapters)
    headers = dict(session.headers)
    cookies = session.cookies.get_dict()
    auth = session.auth
    mount = Mock(wraps=session.mount)
    monkeypatch.setattr(session, "mount", mount)

    client = HttpClient(session=session)

    assert client.session is session
    mount.assert_not_called()
    assert session.adapters == adapters
    assert session.headers == headers
    assert session.cookies.get_dict() == cookies
    assert session.auth == auth

    send = Mock(return_value=make_response())
    monkeypatch.setattr(session, "request", send)
    client.get(URL)
    send.assert_called_once()
    assert send.call_args.args == ("GET", URL)
    client.close()


def test_context_manager_closes_session():
    with HttpClient() as client:
        close = Mock(wraps=client.session.close)
        client.session.close = close

    close.assert_called_once_with()


def test_authorization_and_body_secrets_are_not_logged(client, monkeypatch, caplog):
    secret = "test-token-must-not-be-logged"
    monkeypatch.setattr(client.session, "request", lambda *args, **kwargs: make_response())

    with caplog.at_level(logging.INFO, logger="movebank.infrastructure.http.client"):
        client.post(
            URL,
            headers={"Authorization": f"Bearer {secret}"},
            json={"password": secret},
        )

    assert secret not in caplog.text
    assert "Authorization" not in caplog.text


def test_retries_are_limited_to_get(client):
    retries = client.session.get_adapter("https://").max_retries

    assert isinstance(client.session, requests.Session)
    assert client.session.get_adapter("http://") is client.session.get_adapter("https://")
    assert isinstance(retries, Retry)
    assert retries.total == 3
    assert retries.allowed_methods == frozenset({"GET"})
    assert retries.connect == 0
    assert retries.read == 0
    assert retries.other == 0
    assert retries.status == 3
    assert retries.backoff_factor == 1
    assert set(retries.status_forcelist) == {429, 500, 502, 503, 504}
    assert retries.respect_retry_after_header is True
    assert retries.raise_on_status is False


def test_get_retries_after_503_and_recovers(client, monkeypatch):
    calls = mock_http_responses(monkeypatch, [503, 200])

    result = client.get("http://example.test/animals")

    assert result.status_code == 200
    assert result.text == "OK"
    assert [status for _, _, status in calls] == [503, 200]


def test_get_returns_final_503_as_http_status_error(client, monkeypatch):
    calls = mock_http_responses(monkeypatch, [503, 503, 503, 503])

    with pytest.raises(HttpStatusError) as error:
        client.get("http://example.test/animals")

    assert error.value.response.status_code == 503
    assert error.value.response.text == "Unavailable"
    assert len(calls) == 4


@pytest.mark.parametrize(
    ("method", "verb"),
    [
        ("post", "POST"),
        ("put", "PUT"),
        ("patch", "PATCH"),
        ("delete", "DELETE"),
    ],
)
def test_non_get_methods_are_not_retried_on_transient_status(client, monkeypatch, method, verb):
    calls = mock_http_responses(monkeypatch, [503, 200])

    with pytest.raises(HttpStatusError):
        getattr(client, method)("http://example.test/animals")

    assert calls == [(verb, "/animals", 503)]
