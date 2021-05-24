import asyncio
import functools
import logging
from enum import Enum
from typing import Union

import asyncio_dgram


class State(Enum):
    ON = 2
    OFF = 3
    ERROR = 4


class AnswerException(Exception):
    pass


def auto_recover(func):
    """Make method, called on TcpCommandSocket, automatically recover on error"""

    @functools.wraps(func)
    def auto_recover_wrapper(self, *args, **kwargs):
        # Try 2 times with recovery
        for nTry in range(1, 3):
            try:
                return func(self, *args, **kwargs)
            except ConnectionError as e:
                logging.warning("ConnectionError in auto-recover-decorated method, "
                                "will log exception, reconnect socket and retry...")
                logging.exception(e)
        # Try last time without recovery
        return func(self, *args, **kwargs)

    return auto_recover_wrapper


def check_answer(expected: list, received: list):
    for exp, comp in zip(expected, received):
        if exp is not None and exp != comp:
            raise AnswerException("Answer has unexpected format, expected %s, received %s"
                                  % (str(expected), str(received)))


def convert_int_to_half_bytes(integer: int) -> list:
    result = []
    i = integer
    while i > 16:
        result.append(i % 16)
        i //= 16
    result.append(i)
    while len(result) < 4:
        result.append(0)
    result.reverse()
    logging.debug("Convert: %d -> %s" % (integer, str(result)))
    return result


def convert_half_bytes_int(half_bytes: list) -> int:
    result = 0
    for b in half_bytes:
        if b > 15:
            raise Exception("Invalid byte value %d, only low half must be used!" % b)
        result = result * 16 + b
    logging.debug("Convert: %s -> %d" % (str(half_bytes), result))
    return result


class CommandSocket:
    SPEED = 0x18

    def __init__(self, ip: str, tcp_port: int):
        self.ip = ip
        self.port = tcp_port
        self.recall_task = None

    async def __exec(self, command: list, is_inq=False) -> Union[list, None]:
        sock = None
        try:
            sock = await asyncio_dgram.connect((self.ip, self.port))
            command_bytes = bytes(command)
            await sock.send(command_bytes)
            logging.debug("Command sent: %s" % command_bytes.hex(" "))
            if is_inq:
                result, _remote_address = await sock.recv()
                logging.debug("Answer received: %s" % result.hex(" "))
                return list(result)
            else:
                for _ in range(2):
                    result, _remote_address = await sock.recv()
                    logging.debug("Answer received: %s" % result.hex(" "))
        finally:
            if sock:
                sock.close()

    async def cam_power(self, state: State):
        await self.__exec([0x81, 0x01, 0x04, 0x00, state.value, 0xFF])

    async def cam_power_inq(self) -> State:
        result = await self.__exec([0x81, 0x09, 0x04, 0x00, 0xFF], True)
        check_answer([0x90, 0x50, None, 0xFF], result)
        return State(result[2])

    async def cam_iris_direct(self, iris: int):
        if not 0 <= iris <= 255:
            raise Exception("Invalid iris value %d." % iris)
        await self.__exec([0x81, 0x01, 0x04, 0x4B] + convert_int_to_half_bytes(iris) + [0xFF])

    async def cam_focus_direct(self, focus: int):
        if not 0 <= focus <= 1770:
            raise Exception("Invalid focus value %d." % focus)
        await self.__exec([0x81, 0x01, 0x04, 0x48] + convert_int_to_half_bytes(focus) + [0xFF])

    async def cam_focus_inq(self) -> int:
        answer = await self.__exec([0x81, 0x09, 0x04, 0x48, 0xFF], True)
        check_answer([0x90, 0x50, None, None, None, None, 0xFF], answer)
        return convert_half_bytes_int(answer[2:6])

    async def cam_zoom_inq(self) -> int:
        answer = await self.__exec([0x81, 0x09, 0x04, 0x47, 0xFF], True)
        check_answer([0x90, 0x50, None, None, None, None, 0xFF], answer)
        return convert_half_bytes_int(answer[2:6])

    async def cam_focus_lock(self, state: State):
        await self.__exec([0x81, 0x0A, 0x04, 0x68, state.value, 0xFF])

    async def cam_memory_set(self, pos: int):
        if not 0 <= pos <= 127:
            raise Exception("Invalid position {}.".format(pos))
        await self.__exec([0x81, 0x01, 0x04, 0x3F, 0x01, pos, 0xFF])

    async def __cam_memory_recall(self, pos: int):
        """Internal function for recall execution"""

        if not 0 <= pos <= 127:
            raise Exception("Invalid position {}.".format(pos))
        await self.__exec([0x81, 0x01, 0x06, 0x01, self.SPEED, 0xFF])
        await self.__exec([0x81, 0x01, 0x04, 0x3F, 0x02, pos, 0xFF])

    async def perform_recall(self, pos: int, focus: int):
        """Perform a recall with a certain position and focus value."""

        if self.recall_task is not None and not self.recall_task.done():
            self.recall_task.cancel()

        async def recall_wrapper(pos_int, focus_int):
            # Start recall and immediately request focus adjustment concurrently and await completion
            await asyncio.wait([self.__cam_memory_recall(pos_int), self.cam_focus_direct(focus_int)])
            # Final focus position fixing (recall mostly causes slight shift)
            await self.cam_focus_direct(focus_int)

        self.recall_task = asyncio.create_task(recall_wrapper(pos, focus))
