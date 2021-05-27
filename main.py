import asyncio
import json
import logging
import threading

import websockets
from flask import Flask, render_template
from websockets import WebSocketServerProtocol

from constants import TALLY_IDS, CAMERA_IPS, VISCA_UDP_PORT, SERVER_HOST, FLASK_SERVER_PORT, \
    WEBSOCKET_SERVER_PORT, WEB_TITLE, VISCA_TIMEOUT, RECALL_TIMEOUT
from db import Database
from tally import watch_tallies
from visca import CommandSocket, State

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s %(filename)s:%(lineno)d %(message)s"
)

CAMERAS = None
TALLY_STATES = [0] * len(TALLY_IDS)
DB = Database()
USERS = set()


async def update_button(message: str, data: dict, sender: WebSocketServerProtocol):
    DB.set_button(**data)
    if len(USERS) > 1:  # asyncio.wait doesn't accept an empty list
        logging.debug("Updating users...")
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
            "tally_states": TALLY_STATES
        }
    }))


async def dispatcher(websocket: WebSocketServerProtocol, _path: str):
    USERS.add(websocket)
    try:
        await init(websocket)
        async for message in websocket:
            message_data = json.loads(message)
            event = message_data["event"]
            data = message_data["data"]
            if event == "update_button":
                await asyncio.wait_for(update_button(message, data, websocket), VISCA_TIMEOUT)
            elif event == "save_pos":
                await asyncio.wait_for(save_pos(data), VISCA_TIMEOUT)
            elif event == "recall_pos":
                await asyncio.wait_for(recall_pos(data), RECALL_TIMEOUT)
            elif event == "focus_lock":
                await asyncio.wait([asyncio.create_task(camera.set_focus_lock(State.ON)) for camera in CAMERAS],
                                   timeout=VISCA_TIMEOUT)
            elif event == "focus_unlock":
                await asyncio.wait([asyncio.create_task(camera.set_focus_lock(State.OFF)) for camera in CAMERAS],
                                   timeout=VISCA_TIMEOUT)
            elif event == "power_on":
                await asyncio.wait([asyncio.create_task(camera.set_power(State.ON)) for camera in CAMERAS],
                                   timeout=VISCA_TIMEOUT)
            elif event == "power_off":
                await asyncio.wait([asyncio.create_task(camera.set_power(State.OFF)) for camera in CAMERAS],
                                   timeout=VISCA_TIMEOUT)
            elif event == "clear_all":
                DB.clear_buttons()
                await asyncio.wait([asyncio.create_task(init(user)) for user in USERS])
            else:
                logging.error("Unsupported event: %s with data %s" % (event, data))
    finally:
        USERS.remove(websocket)


async def tally_notify(cam: int, state: int):
    TALLY_STATES[cam] = state
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

    # Wait on event loop
    asyncio.get_event_loop().run_forever()
