import asyncio
import logging
from asyncio import StreamReader, StreamWriter, CancelledError, Task
from typing import Awaitable, Callable, List, Optional

from constants import TALLY_IDS, TALLY_HOST, TALLY_PORT

LOG = logging.getLogger("tally")
watch_task: Optional[Task] = None


async def stop_watcher():
    watch_task.cancel()


async def watch_tallies(tally_notify: Callable[[int, int], Awaitable[None]]):
    global watch_task
    # Create and schedule tally watcher clients
    watch_task = asyncio.create_task(watch(TALLY_IDS, tally_notify, TALLY_HOST, TALLY_PORT))


async def connect(tally_ids: List[int], host: str, port: int) -> (StreamReader, StreamWriter):
    reader, writer = await asyncio.open_connection(host, port)
    # Request new format
    writer.write(b'\xff')
    writer.write(len(tally_ids).to_bytes(1, 'big'))
    for tally_id in tally_ids:
        writer.write(tally_id.to_bytes(1, 'big'))
    await writer.drain()
    return reader, writer


async def watch(tally_ids: List[int], callback: Callable[[int, int], Awaitable[None]], host: str, port: int):
    # Start with a 1-second reconnect delay on first error (see doubling below)
    reconnect_delay = 0.5
    tally_map = {tally_cam: cam for cam, tally_cam in enumerate(TALLY_IDS)}
    last_states = [0] * len(tally_ids)
    LOG.info("Connecting to tally state monitoring for devices %s" % str(tally_ids))
    writer = None
    while True:
        try:
            if reconnect_delay > 0.5:
                LOG.error("Error, try reconnect after %d s..." % reconnect_delay)
                await asyncio.sleep(reconnect_delay)
            reader, writer = await connect(tally_ids, host, port)
            while True:
                state_bytes = await reader.readexactly(2)
                # Handle keep-alive
                if state_bytes == b'\xff\xff':
                    continue
                # Upon success, reset reconnect delay to initial value
                reconnect_delay = 0.5
                # Extract bytes: First tally cam ID, second state value
                tally_cam, state = state_bytes
                cam = tally_map[tally_cam]
                if state != last_states[cam]:
                    LOG.info("Switched tally state %d => %d for PTZ %d" % (last_states[cam], state, cam + 1))
                    last_states[cam] = state
                    await callback(cam, state)
                else:
                    LOG.debug("Received unchanged tally state %d for PTZ %d" % (state, cam + 1))
        except CancelledError:
            if writer is not None:
                # Close connection without awaiting result
                writer.close()
            logging.debug("Tally watcher for devices %s cancelled" % str(tally_ids))
            return
        except Exception as e:
            logging.exception(e)
            if writer is not None:
                # Close possibly broken connection, do not await result (wait_close())
                writer.close()
            # Increase delay exponentially
            reconnect_delay = min(reconnect_delay * 2, 20)
