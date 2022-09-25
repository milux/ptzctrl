import asyncio
import json
import logging
import threading
from asyncio.exceptions import TimeoutError
from typing import Optional, List

import websockets
from flask import Flask, render_template
from websockets import WebSocketServerProtocol

from constants import TALLY_IDS, CAMERA_IPS, VISCA_UDP_PORT, SERVER_HOST, FLASK_SERVER_PORT, \
    WEBSOCKET_SERVER_PORT, WEB_TITLE, VISCA_TIMEOUT, RECALL_TIMEOUT
from db import Database
from relay import run_relay
from tally import watch_tallies, stop_watcher
from visca import CommandSocket, State

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

LOG = logging.getLogger("main")
CAMERAS = None
TALLY_STATES = [0] * len(TALLY_IDS)
IP_HOLDER: List[Optional[str]] = [None]
DB = Database()
USERS = set()
on_air_change_allowed = False


async def update_button(message: str, data: dict, sender: WebSocketServerProtocol):
    DB.set_button(**data)
    if len(USERS) > 1:  # asyncio.wait doesn't accept an empty list
        LOG.debug("Updating users...")
        await asyncio.wait([asyncio.create_task(user.send(message)) for user in USERS if user != sender])


async def save_pos(data: dict):
    camera = CAMERAS[data["cam"]]
    focus = await camera.inq_focus()
    DB.set_focus(focus=focus, **data)
    await camera.memory_set(data["pos"])


async def recall_pos(data: dict):
    camera = CAMERAS[data["cam"]]
    focus = DB.get_focus(**data)
    await camera.recall(data["pos"], focus)


async def init(user: WebSocketServerProtocol):
    await user.send(json.dumps({
        "event": "init",
        "data": {
            "camera_ips": CAMERA_IPS,
            "all_pos": DB.get_data(),
            "tally_states": TALLY_STATES,
            "on_air_change_allowed": on_air_change_allowed
        }
    }))


async def update_on_air_change(allow: bool, sender: WebSocketServerProtocol):
    global on_air_change_allowed
    on_air_change_allowed = allow
    # Update relay state if there is a camera that is selected for preview and program
    for cam, state in enumerate(TALLY_STATES):
        if state == 3:
            update_relay_ip(cam, state)
    if len(USERS) > 1:  # asyncio.wait doesn't accept an empty list
        message = json.dumps({
            "event": "update_on_air_change",
            "data": on_air_change_allowed
        })
        LOG.debug("Updating users (On Air Change)...")
        await asyncio.wait([asyncio.create_task(user.send(message)) for user in USERS if user != sender])


async def dispatcher(websocket: WebSocketServerProtocol, _path: str):
    USERS.add(websocket)
    try:
        await init(websocket)
        async for message in websocket:
            message_data = json.loads(message)
            event = message_data["event"]
            data = message_data["data"]
            try:
                if event == "update_button":
                    await asyncio.wait_for(update_button(message, data, websocket), VISCA_TIMEOUT)
                elif event == "save_pos":
                    await asyncio.wait_for(save_pos(data), VISCA_TIMEOUT)
                elif event == "recall_pos":
                    await asyncio.wait_for(recall_pos(data), RECALL_TIMEOUT)
                elif event == "focus_lock":
                    await asyncio.wait([asyncio.create_task(camera.set_focus_lock(State.ON if data else State.OFF))
                                        for camera in CAMERAS],
                                       timeout=VISCA_TIMEOUT)
                elif event == "power":
                    await asyncio.wait([asyncio.create_task(camera.set_power(State.ON if data else State.OFF))
                                        for camera in CAMERAS],
                                       timeout=VISCA_TIMEOUT)
                elif event == "allow_on_air_change":
                    await asyncio.wait_for(update_on_air_change(data, websocket), VISCA_TIMEOUT)
                elif event == "clear_all":
                    DB.clear_buttons()
                    await asyncio.wait([asyncio.create_task(init(user)) for user in USERS])
                elif event == "reconnect":
                    await stop_watcher()
                    await watch_tallies(tally_notify)
                else:
                    LOG.error("Unsupported event: %s with data %s" % (event, data))
            except TimeoutError as e:
                LOG.warning("Timeout error during visca operation", exc_info=e)
    finally:
        USERS.remove(websocket)


def update_relay_ip(cam: int, state: int):
    if state == 1 or (on_air_change_allowed and (state & 0x1) == 0x1):
        IP_HOLDER[0] = CAMERA_IPS[cam]
        LOG.debug(">>> Relay PTZ %d (%s)" % (cam + 1, CAMERA_IPS[cam]))
    elif IP_HOLDER[0] == CAMERA_IPS[cam]:
        IP_HOLDER[0] = None
        LOG.debug(">>> Relay disabled")


async def tally_notify(cam: int, state: int):
    TALLY_STATES[cam] = state
    update_relay_ip(cam, state)
    if USERS:
        message = json.dumps({
            "event": "update_tally",
            "data": TALLY_STATES
        })
        await asyncio.wait([asyncio.create_task(user.send(message)) for user in USERS])


if __name__ == "__main__":
    # Create flask web server for resource serving
    app = Flask(__name__)

    @app.route('/')
    def root():
        return render_template('index.html', title=WEB_TITLE)

    # Start flask server in separate Thread
    threading.Thread(
        target=app.run,
        kwargs={"use_reloader": False, "host": SERVER_HOST, "port": FLASK_SERVER_PORT},
        daemon=True).start()

    # Init camera controls
    CAMERAS = [CommandSocket(ip, VISCA_UDP_PORT) for ip in CAMERA_IPS]
    # Start WebSocket server
    start_server = websockets.serve(dispatcher, SERVER_HOST, WEBSOCKET_SERVER_PORT)
    asyncio.get_event_loop().run_until_complete(start_server)

    # Start tally state watcher clients
    asyncio.get_event_loop().run_until_complete(watch_tallies(tally_notify))

    asyncio.get_event_loop().run_until_complete(run_relay(IP_HOLDER))

    # Wait on event loop
    asyncio.get_event_loop().run_forever()
