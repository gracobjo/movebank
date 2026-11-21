"""Run Movebank operations with an interface-provided license decision."""

from collections.abc import Callable

from movebank.infrastructure.movebank.client import LicenseRequired


class ConsentRejected(Exception):
    """The user declined the Movebank license terms."""


def run_with_consent[T](
    action: Callable[[str | None], T],
    confirm: Callable[[LicenseRequired], bool],
) -> T:
    """Run an action, asking the caller to confirm each distinct license MD5.

    Accepted hashes are scoped to this call only. If the same license is
    requested again after retrying, the request is propagated instead of
    prompting indefinitely.
    """
    approved_md5: str | None = None
    prompted_md5s: set[str] = set()

    while True:
        try:
            return action(approved_md5)
        except LicenseRequired as request:
            if request.md5 in prompted_md5s:
                raise
            if not confirm(request):
                raise ConsentRejected(
                    "Licencia no aceptada; no se han descargado los datos."
                ) from None
            prompted_md5s.add(request.md5)
            approved_md5 = request.md5
