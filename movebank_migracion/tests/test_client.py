import hashlib
from unittest.mock import Mock

import pytest
import requests

from movebank.infrastructure.movebank.client import LicenseRequired, MovebankClient, MovebankError
from movebank.infrastructure.movebank.services import (
    MovebankEventService,
    MovebankIndividualService,
    MovebankStudyService,
)


def response(content: bytes, status: int = 200) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result._content = content
    result.url = "https://www.movebank.org"
    result.encoding = "utf-8"
    result.headers["Content-Type"] = "text/csv"
    return result


def test_csv_and_services(monkeypatch):
    client = MovebankClient(interval=0)
    calls = []

    def request(method, url, **kwargs):
        params = kwargs["params"]
        calls.append((method, url, kwargs))
        if params["entity_type"] == "study":
            return response(b"id,name\n1,Study\n")
        if params["entity_type"] == "individual":
            return response(b"id,local_identifier\n2,Bird\n")
        return response(
            b"event_id,individual_id,timestamp,location_lat,location_long,visible,individual_taxon_canonical_name\n"
        )

    monkeypatch.setattr(client.session, "request", request)
    assert MovebankStudyService(client).list()[0]["id"] == "1"
    assert MovebankIndividualService(client).list(1)[0]["id"] == "2"
    assert MovebankEventService(client).list(1, 2) == []
    assert calls[-1][0:2] == ("GET", "https://www.movebank.org/movebank/service/direct-read")
    assert calls[-1][2]["params"]["sensor_type_id"] == 653
    assert calls[-1][2]["params"]["individual_id"] == 2
    assert calls[-1][2]["timeout"] == (15, 120)
    client.close()


def test_license_requires_explicit_matching_consent(monkeypatch):
    client = MovebankClient(interval=0)
    terms = b"<html>License Terms: test</html>"
    digest = hashlib.md5(terms, usedforsecurity=False).hexdigest()
    calls = []

    def request(method, url, **kwargs):
        params = kwargs["params"]
        calls.append(params)
        if params.get("license-md5") == digest:
            return response(b"id,name\n1,Study\n")
        return response(terms)

    monkeypatch.setattr(client.session, "request", request)
    with pytest.raises(LicenseRequired) as exc:
        client.read({"entity_type": "study"})
    assert exc.value.md5 == digest
    with pytest.raises(LicenseRequired):
        client.read({"entity_type": "study"}, "wrong")
    assert client.read({"entity_type": "study"}, digest)[0]["id"] == "1"
    assert calls[-1]["license-md5"] == digest
    client.close()


@pytest.mark.parametrize(
    "body", [b"<html>failed</html>", b"wrong,columns\nx,y", b"id,name\n1,a,extra", b"id,name\n1"]
)
def test_invalid_responses_are_errors(monkeypatch, body):
    client = MovebankClient(interval=0)
    monkeypatch.setattr(client.session, "request", lambda *a, **k: response(body))
    with pytest.raises(MovebankError):
        client.read({"entity_type": "study"})


def test_http_and_configuration_errors(monkeypatch):
    with pytest.raises(ValueError):
        MovebankClient("user", None)
    with pytest.raises(ValueError):
        MovebankClient(interval=-1)
    client = MovebankClient(interval=0)
    monkeypatch.setattr(client.session, "request", lambda *a, **k: response(b"unauthorized", 401))
    with pytest.raises(MovebankError) as error:
        client.read({"entity_type": "study"})
    assert error.value.status_code == 401
    assert error.value.response.status_code == 401


def test_rate_limit_waits_before_sending(monkeypatch):
    import movebank.infrastructure.movebank.client as movebank_client_module

    client = MovebankClient(interval=1.0)
    events = []
    clock = iter([20.5, 21.0])
    monkeypatch.setattr(movebank_client_module, "_last_request", 20.0)
    monkeypatch.setattr(movebank_client_module.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(
        movebank_client_module.time,
        "sleep",
        lambda delay: events.append(("sleep", delay)),
    )

    def request(*args, **kwargs):
        events.append(("request", kwargs["timeout"]))
        return response(b"id,name\n1,Study\n")

    monkeypatch.setattr(client.session, "request", request)
    assert client.read({"entity_type": "study"})[0]["id"] == "1"
    assert events == [("sleep", 0.5), ("request", (15, 120))]
    client.close()


def test_close_closes_session_once():
    client = MovebankClient(interval=0)
    close = Mock(wraps=client.session.close)
    client.session.close = close

    client.close()

    close.assert_called_once_with()
