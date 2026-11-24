from intake.catalog import AcceptedPacket, IntakeCatalog
from intake.verify import verify_packet


def receive(catalog: IntakeCatalog, packet: bytes) -> AcceptedPacket:
    verified = verify_packet(packet)
    return catalog.accept(verified)
