from typing import Optional, List

import asyncio_dgram


async def run_relay(ip_holder: List[Optional[str]]):
    sock = await asyncio_dgram.bind(('0.0.0.0', 1259))
    client_addr = None

    while True:
        try:
            data, addr = await sock.recv()

            if ip_holder[0] is None:
                # Without a valid destiny, incoming UDP segments will be ignored
                continue
            else:
                known_server = (ip_holder[0], 1259)

            if addr == known_server:
                # Safety check, should actually be impossible since that would be a response without a prior request
                if client_addr is not None:
                    await sock.send(data, client_addr)
            else:
                client_addr = addr
                await sock.send(data, known_server)
        except Exception as e:
            print("Error in relay: %s" % e)
