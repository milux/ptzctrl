import asyncio
import logging
from asyncio import StreamReader, StreamWriter
from typing import Awaitable, Callable

from constants import TALLY_IDS, TALLY_HOST, TALLY_PORT

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
    # Start with only 10 ms reconnect delay on first error
    reconnect_delay = 10
    logging.info("Connecting to tally state monitoring for device %d (PTZ %d)" % (tally_cam, cam))
    reader, writer = await connect(tally_cam, host, port)
    while True:
        state_bytes = await reader.read(1)
        while len(state_bytes) == 0:
            # Close possibly broken connection, do not await result (wait_close())
            writer.close()
            # Convert reconnect delay to seconds
            delay = reconnect_delay / 1000
            logging.error("Received no update for device %d, try reconnect after %d s..." % (tally_cam, delay))
            await asyncio.sleep(delay)
            reader, writer = await connect(tally_cam, host, port)
            state_bytes = await reader.read(1)
            # Increase delay exponentially
            reconnect_delay = max(reconnect_delay * 2, 20000)
        # Upon success, reset reconnect delay to initial value
        reconnect_delay = 10
        state = int.from_bytes(state_bytes, 'big')
        logging.info("Received state %d for PTZ %d" % (state, cam))
        await callback(cam, state)
