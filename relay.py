import asyncio
import logging
from typing import Optional, List


LOG = logging.getLogger("relay")


async def run_relay(ip_holder: List[Optional[str]]):
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: DatagramProtocol(ip_holder),
        local_addr=('0.0.0.0', 1259)
    )
    return transport


class DatagramProtocol(asyncio.DatagramProtocol):
    def __init__(self, ip_holder: List[Optional[str]]):
        self.ip_holder = ip_holder
        self.client_addr = None
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport

    def connection_lost(self, _exc):
        self.transport.close()

    def error_received(self, exc):
        LOG.error("Error in UDP relay transport")
        logging.exception(exc)

    def datagram_received(self, data, addr):
        if not self.ip_holder[0]:
            # Without a valid destination, incoming UDP segments will be ignored
            return
        else:
            known_server = (self.ip_holder[0], 1259)

        if addr == known_server:
            # Safety check, should actually be impossible since that would be a response without a prior request
            if self.client_addr is not None:
                self.transport.sendto(data, self.client_addr)
        else:
            self.client_addr = addr
            self.transport.sendto(data, known_server)
