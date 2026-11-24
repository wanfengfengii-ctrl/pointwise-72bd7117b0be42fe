from intake.catalog import AcceptedPacket, IntakeCatalog
from intake.receipt import IntakeReceipt
from intake.verify import verify_packet, verify_window_packet
from issue.window import require_window


def receive(catalog: IntakeCatalog, packet: bytes) -> AcceptedPacket:
    verified = verify_packet(packet)
    return catalog.accept(verified)


def pin_window_issue(intake: IntakeCatalog, station: str, issue_id: int, credential: bytes) -> None:
    """Preload the trusted credential for one issuance; the caller never inspects it."""
    intake.pin(station, issue_id, credential)


def receive_window(
    intake: IntakeCatalog,
    station: str,
    issue_id: int,
    lo: object,
    hi: object,
    packet: bytes,
) -> IntakeReceipt:
    """Accept a window delivery addressed by its issuance and request window."""
    window = require_window(lo, hi)
    credential = intake.get_pin(station, issue_id)
    if credential is None:
        raise ValueError(
            f'no pinned credential for station {station!r} and issue {issue_id!r}'
        )
    try:
        fields = verify_window_packet(packet, station, issue_id, window, credential)
    except ValueError as error:
        raise ValueError(str(error)) from error
    return intake.accept_window(fields, packet, window)
