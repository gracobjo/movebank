import pytest

from movebank.infrastructure.movebank.client import LicenseRequired
from movebank.infrastructure.movebank.consent import ConsentRejected, run_with_consent


def test_operation_without_license_does_not_request_confirmation():
    calls = []

    def action(approved_md5):
        calls.append(approved_md5)
        return "result"

    assert run_with_consent(action, lambda _: pytest.fail("unexpected consent prompt")) == "result"
    assert calls == [None]


def test_acceptance_retries_with_the_requested_md5():
    request = LicenseRequired(b"License Terms: first")
    calls = []
    prompts = []

    def action(approved_md5):
        calls.append(approved_md5)
        if approved_md5 is None:
            raise request
        return approved_md5

    assert (
        run_with_consent(action, lambda license_request: prompts.append(license_request) or True)
        == request.md5
    )
    assert calls == [None, request.md5]
    assert prompts == [request]


def test_rejection_stops_without_retrying():
    request = LicenseRequired(b"License Terms: first")
    calls = []

    def action(approved_md5):
        calls.append(approved_md5)
        raise request

    with pytest.raises(ConsentRejected, match="Licencia no aceptada"):
        run_with_consent(action, lambda _: False)
    assert calls == [None]


def test_distinct_second_license_requires_a_second_confirmation():
    first = LicenseRequired(b"License Terms: first")
    second = LicenseRequired(b"License Terms: second")
    calls = []
    prompts = []

    def action(approved_md5):
        calls.append(approved_md5)
        if approved_md5 is None:
            raise first
        if approved_md5 == first.md5:
            raise second
        return approved_md5

    result = run_with_consent(action, lambda request: prompts.append(request) or True)

    assert result == second.md5
    assert calls == [None, first.md5, second.md5]
    assert prompts == [first, second]


def test_same_license_after_retry_is_not_prompted_or_retried_forever():
    request = LicenseRequired(b"License Terms: unchanged")
    calls = []
    prompts = []

    def action(approved_md5):
        calls.append(approved_md5)
        raise request

    with pytest.raises(LicenseRequired) as error:
        run_with_consent(action, lambda value: prompts.append(value) or True)

    assert error.value is request
    assert calls == [None, request.md5]
    assert prompts == [request]
