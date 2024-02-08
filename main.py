import asyncio
import logging
from asyncio.exceptions import TimeoutError
from contextlib import asynccontextmanager, closing
from typing import Optional, List, Any, Set

from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import HTMLResponse
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates
from starlette.websockets import WebSocket, WebSocketDisconnect

from constants import TALLY_IDS, CAMERA_IPS, VISCA_UDP_PORT, WEB_TITLE, VISCA_TIMEOUT, RECALL_TIMEOUT
from db import Database
from relay import run_relay
from tally import watch_tallies, stop_watcher
from visca import CommandSocket, State

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

LOG = logging.getLogger("main")
CAMERAS: List[CommandSocket]
TALLY_STATES = [0] * len(TALLY_IDS)
IP_HOLDER: List[Optional[str]] = [None]
DB: Database
USERS: Set[WebSocket] = set()
on_air_change_allowed = False


async def update_button(message: Any, data: dict, sender: WebSocket):
    DB.set_button(**data)
    if len(USERS) > 1:  # asyncio.wait doesn't accept an empty list
        LOG.debug("Updating users...")
        await asyncio.wait([asyncio.create_task(user.send_json(message)) for user in USERS if user != sender])


async def save_pos(data: dict):
    camera = CAMERAS[data["cam"]]
    focus = await camera.inq_focus()
    DB.set_focus(focus=focus, **data)
    await camera.memory_set(data["pos"])


async def recall_pos(data: dict):
    camera = CAMERAS[data["cam"]]
    focus = DB.get_focus(**data)
    await camera.recall(data["pos"], focus)


async def init(user: WebSocket):
    await user.send_json({
        "event": "init",
        "data": {
            "camera_ips": CAMERA_IPS,
            "all_pos": DB.get_data(),
            "tally_states": TALLY_STATES,
            "on_air_change_allowed": on_air_change_allowed
        }
    })


async def update_on_air_change(allow: bool, sender: WebSocket):
    global on_air_change_allowed
    on_air_change_allowed = allow
    # Update relay state if there is a camera that is selected for preview and program
    for cam, state in enumerate(TALLY_STATES):
        if state == 3:
            update_relay_ip(cam, state)
    if len(USERS) > 1:  # asyncio.wait doesn't accept an empty list
        message = {
            "event": "update_on_air_change",
            "data": on_air_change_allowed
        }
        LOG.debug("Updating users (On Air Change)...")
        await asyncio.wait([asyncio.create_task(user.send_json(message)) for user in USERS if user != sender])


def update_relay_ip(cam: int, state: int):
    if state == 1 or (on_air_change_allowed and (state & 0x1) == 0x1):
        IP_HOLDER[0] = CAMERA_IPS[cam]
        LOG.debug(f">>> Relay PTZ {cam + 1} ({CAMERA_IPS[cam]})")
    elif IP_HOLDER[0] == CAMERA_IPS[cam]:
        IP_HOLDER[0] = None
        LOG.debug(">>> Relay disabled")


async def tally_notify(cam: int, state: int):
    TALLY_STATES[cam] = state
    update_relay_ip(cam, state)
    if USERS:
        message = {
            "event": "update_tally",
            "data": TALLY_STATES
        }
        await asyncio.wait([asyncio.create_task(user.send_json(message)) for user in USERS])


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global CAMERAS, DB
    try:
        # Init camera controls
        CAMERAS = [CommandSocket(ip, VISCA_UDP_PORT) for ip in CAMERA_IPS]
        # Open database
        DB = Database()
        # Start tally state watcher client
        watch_tallies(tally_notify)
        # Start VISCA relay
        with closing(await run_relay(IP_HOLDER)):
            # Run FastAPI server
            yield
    finally:
        # Terminate tally state watcher
        await stop_watcher()


app = FastAPI(lifespan=lifespan)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "title": WEB_TITLE})


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    ws_client = websocket.client
    LOG.info(f"Websocket client {(ws_client.host, ws_client.port)} connected")
    USERS.add(websocket)
    try:
        await init(websocket)
        while True:
            message = await websocket.receive_json()
            event = message["event"]
            data = message["data"]
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
                    watch_tallies(tally_notify)
                else:
                    LOG.error(f"Unsupported event: {event} with data {data}")
            except TimeoutError as e:
                LOG.warning("Timeout error during visca operation", exc_info=e)
    except WebSocketDisconnect as d:
        LOG.info(f"Websocket client {(ws_client.host, ws_client.port)} disconnected with code {d.code}")
    finally:
        USERS.remove(websocket)
