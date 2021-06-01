import asyncio
import logging
from asyncio import StreamReader, StreamWriter
from typing import Awaitable, Callable

from constants import TALLY_IDS, TALLY_HOST, TALLY_PORT

LOG = logging.getLogger("tally")
TALLY_WATCH_TASKS = []


async def watch_tallies(tally_notify: Callable[[int, int], Awaitable[None]]):
    # Create and schedule tally watcher clients
    for index, num in enumerate(TALLY_IDS):
        TALLY_WATCH_TASKS.append(asyncio.create_task(watch(index, num, tally_notify, TALLY_HOST, TALLY_PORT)))


async def connect(tally_cam: int, host: str, port: int) -> (StreamReader, StreamWriter):
    reader, writer = await asyncio.open_connection(host, port)
    writer.write(tally_cam.to_bytes(1, 'big'))
    await writer.drain()
    return reader, writer


async def watch(cam: int, tally_cam: int, callback: Callable[[int, int], Awaitable[None]], host: str, port: int):
    # Start with only 100 ms reconnect delay on first error
    reconnect_delay_ms = 50
    LOG.info("Connecting to tally state monitoring for device %d (PTZ %d)" % (tally_cam, cam))
    while True:
        try:
            if reconnect_delay_ms > 50:
                # Convert reconnect delay to seconds
                delay_s = reconnect_delay_ms / 1000
                LOG.error("Error for device %d, try reconnect after %.2f s..." % (tally_cam, delay_s))
                await asyncio.sleep(delay_s)
            reader, writer = await connect(tally_cam, host, port)
            while True:
                state_bytes = await reader.read(1)
                if len(state_bytes) == 0:
                    # Close possibly broken connection, do not await result (wait_close())
                    writer.close()
                    raise Exception("Received empty tally response for PTZ %d" % cam)
                else:
                    # Upon success, reset reconnect delay to initial value
                    reconnect_delay_ms = 50
                state = int.from_bytes(state_bytes, 'big')
                LOG.info("Received state %d for PTZ %d" % (state, cam))
                await callback(cam, state)
        except Exception as e:
            logging.exception(e)
            # Increase delay exponentially
            reconnect_delay_ms = min(reconnect_delay_ms * 2, 20000)
