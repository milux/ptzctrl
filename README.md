# PTZ control tool

This project aims to provide a tool for the management of PTZ cameras, especially via touch devices.
The tool communicates with PTZ cameras via the VISCA UDP/IP protocol.

It provides (per default) 18 buttons for a (theoretically) unlimited number of PTZ cameras.
(In practice, more than 3 PTZ cameras may result in poor interface usability.)

The control logic is processed centrally in a python service and synced across all (web) clients using WebSockets.

In order to run the tool, usage of `docker`/`docker-compose` is recommended.

### Python requirements

If you want to start the tool manually via its entry point (`main.py`),
the following (`pip`) dependencies must be installed **in addition to Python 3.8 or higher**:

- websockets (9.x)
- flask (2.x)
- asyncio-dgram (2.x)

### Setup

The default settings of this tool match specifically our setup.
Please adapt `constants.py`, using sane values that fit your setup.