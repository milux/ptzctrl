import asyncio
import logging
from asyncio import StreamReader, StreamWriter, CancelledError, Task
from typing import Awaitable, Callable, List, Optional

from constants import TALLY_IDS, TALLY_HOST, TALLY_PORT, TALLY_KEEPALIVE_FREQUENCY

LOG = logging.getLogger("tally")
watch_task: Optional[Task] = None


async def stop_watcher():
    watch_task.cancel()
    try:
        await watch_task
    except CancelledError:
        pass


def watch_tallies(tally_notify: Callable[[int, int], Awaitable[None]]):
    global watch_task
    # Create and schedule tally watcher clients
    watch_task = asyncio.create_task(watch(TALLY_IDS, tally_notify, TALLY_HOST, TALLY_PORT))


async def send_keepalive_messages(writer: StreamWriter):
    try:
        while not writer.is_closing():
            writer.write(b'\xff\xff')
            await writer.drain()
            await asyncio.sleep(TALLY_KEEPALIVE_FREQUENCY)
    except CancelledError:
        LOG.debug("Keepalive task has been cancelled")
    except Exception as e:
        LOG.error("Error whilst sending keep-alive message")
        logging.exception(e)


async def connect(tally_ids: List[int], host: str, port: int) -> (StreamReader, StreamWriter):
    reader, writer = await asyncio.open_connection(host, port)
    # Request new format
    writer.write(b'\xff')
    # Write number of tally IDs
    writer.write(len(tally_ids).to_bytes(1, 'big'))
    # Write tally IDs
    for tally_id in tally_ids:
        writer.write(tally_id.to_bytes(1, 'big'))
    # Await flush
    await writer.drain()
    # Pass on reader/writer pair
    return reader, writer


async def watch(tally_ids: List[int], callback: Callable[[int, int], Awaitable[None]], host: str, port: int):
    # Start with a 1-second reconnect delay on first error (see doubling below)
    reconnect_delay = 0.5
    tally_map = {tally_cam: cam for cam, tally_cam in enumerate(TALLY_IDS)}
    last_states = [0] * len(tally_ids)
    LOG.info(f"Connecting to tally state monitoring for devices {tally_ids}")
    writer = None
    keep_alive_task = None
    while True:
        try:
            if reconnect_delay > 0.5:
                LOG.error(f"Error, try reconnect after {reconnect_delay} s...")
                await asyncio.sleep(reconnect_delay)
            reader, writer = await connect(tally_ids, host, port)
            keep_alive_task = asyncio.create_task(send_keepalive_messages(writer))
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
                    LOG.info(f"Switched tally state {last_states[cam]} => {state} for PTZ {cam + 1}")
                    last_states[cam] = state
                    await callback(cam, state)
                else:
                    LOG.debug(f"Received unchanged tally state {state} for PTZ {cam + 1}")
        except CancelledError:
            logging.debug(f"Tally watcher for devices {tally_ids} cancelled")
            # Exit task
            return
        except Exception as e:
            logging.exception(e)
            # Increase delay exponentially
            reconnect_delay = min(reconnect_delay * 2, 20)
        finally:
            try:
                if writer is not None:
                    # Close connection without awaiting result
                    writer.close()
                if keep_alive_task is not None:
                    # Cancel keepalive message sending
                    keep_alive_task.cancel()
            except:
                pass
