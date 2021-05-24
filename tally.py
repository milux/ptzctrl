import asyncio
import logging


class TallyClient:
    def __init__(self, cam: int, tally_cam: int, async_callback: callable, host: str, port: int):
        self.cam = cam
        self.tally_cam = tally_cam
        self.callback = async_callback
        self.stopped = False
        self.host = host
        self.port = port
        self.reader, self.writer = None, None

    def stop(self):
        self.stopped = True

    async def connect(self):
        logging.info("Connecting to tally state monitoring for device %d (PTZ %d)" % (self.tally_cam, self.cam))
        self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
        self.writer.write(self.tally_cam.to_bytes(1, 'big'))

        while not self.stopped:
            state_byte = await self.reader.read(1)
            state = int.from_bytes(state_byte, 'big')
            logging.info("Received state %d for PTZ %d" % (state, self.cam))
            await self.callback(self.cam, state)
