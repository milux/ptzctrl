import asyncio
import logging
from enum import Enum
from typing import Union

import asyncio_dgram

from constants import VISCA_MEMORY_SPEED

LOG = logging.getLogger("visca")


class State(Enum):
    ON = 2
    OFF = 3
    ERROR = 4


class AnswerException(Exception):
    pass


def check_answer(expected: list, received: list):
    for exp, comp in zip(expected, received):
        if exp is not None and exp != comp:
            raise AnswerException(f"Answer has unexpected format, expected {str(expected)}, received {str(received)}")


def convert_int_to_half_bytes(integer: int) -> list:
    """This function splits the given integer into >= 4 half-filled bytes, ranging from 0x00 to 0x0F"""

    result = []
    i = integer
    while i > 16:
        result.append(i % 16)
        i //= 16
    result.append(i)
    while len(result) < 4:
        result.append(0)
    result.reverse()
    LOG.debug(f"Convert: {integer} -> {result}")
    return result


def convert_half_bytes_int(half_bytes: list) -> int:
    """This function retrieves an integer from half-filled bytes, ranging from 0x00 to 0x0F"""

    result = 0
    for b in half_bytes:
        if b > 15:
            raise Exception(f"Invalid byte value {b}, only low half must be used!")
        result = result * 16 + b
    LOG.debug(f"Convert: {half_bytes} -> {result}")
    return result


class CommandSocket:
    def __init__(self, ip: str, tcp_port: int):
        self.ip = ip
        self.port = tcp_port
        self.recall_task = None
        self.ephemeral_autofocus = False

    async def __exec(self, command: list, is_inq=False) -> Union[list, None]:
        sock = None
        try:
            sock = await asyncio_dgram.connect((self.ip, self.port))
            command_bytes = bytes(command)
            await sock.send(command_bytes)
            LOG.debug(f"Command sent: {command_bytes.hex(' ')}")
            if is_inq:
                result, _remote_address = await sock.recv()
                LOG.debug(f"Answer received: {result.hex(' ')}")
                return list(result)
            else:
                for _ in range(2):
                    result, _remote_address = await sock.recv()
                    LOG.debug(f"Answer received: {result.hex(' ')}")
        finally:
            if sock:
                sock.close()

    async def set_power(self, state: State):
        LOG.debug(f"Set power state: {state}")
        await self.__exec([0x81, 0x01, 0x04, 0x00, state.value, 0xFF])

    async def inq_power(self) -> State:
        result = await self.__exec([0x81, 0x09, 0x04, 0x00, 0xFF], True)
        check_answer([0x90, 0x50, None, 0xFF], result)
        return State(result[2])

    async def set_iris_direct(self, iris: int):
        if not 0 <= iris <= 255:
            raise Exception(f"Invalid iris value {iris}.")
        await self.__exec([0x81, 0x01, 0x04, 0x4B] + convert_int_to_half_bytes(iris) + [0xFF])

    async def focus_direct(self, focus: int):
        LOG.debug(f"Set focus: {focus}")
        if not 0 <= focus <= 1770:
            raise Exception(f"Invalid focus value {focus}.")
        await self.__exec([0x81, 0x01, 0x04, 0x48] + convert_int_to_half_bytes(focus) + [0xFF])

    async def inq_focus(self) -> int:
        answer = await self.__exec([0x81, 0x09, 0x04, 0x48, 0xFF], True)
        check_answer([0x90, 0x50, None, None, None, None, 0xFF], answer)
        return convert_half_bytes_int(answer[2:6])

    async def inq_focus_af_mode(self) -> State:
        result = await self.__exec([0x81, 0x09, 0x04, 0x38, 0xFF], True)
        check_answer([0x90, 0x50, None, 0xFF], result)
        return State(result[2])

    async def inq_zoom(self) -> int:
        answer = await self.__exec([0x81, 0x09, 0x04, 0x47, 0xFF], True)
        check_answer([0x90, 0x50, None, None, None, None, 0xFF], answer)
        return convert_half_bytes_int(answer[2:6])

    async def set_focus_lock(self, state: State):
        LOG.debug(f"Set focus lock state: {state}")
        # In case of a concurrent recall, clear the ephemeral AF flag, since FL overrides this semantically
        if state == State.ON:
            self.ephemeral_autofocus = False
        # Execute or unlock FL
        await self.__exec([0x81, 0x0A, 0x04, 0x68, state.value, 0xFF])
        if state == State.OFF:
            # When focus lock was turned off, instantly request autofocus to obtain a "sane" state
            await self.__exec([0x81, 0x01, 0x04, 0x38, State.ON.value, 0xFF])

    async def memory_set(self, pos: int):
        LOG.debug(f"Save position {pos} to memory")
        if not 0 <= pos <= 127:
            raise Exception(f"Invalid position {pos}.")
        await self.__exec([0x81, 0x01, 0x04, 0x3F, 0x01, pos, 0xFF])

    async def __memory_recall(self, pos: int):
        """Internal function for recall execution"""

        if not 0 <= pos <= 127:
            raise Exception(f"Invalid position {pos}.")
        await self.__exec([0x81, 0x01, 0x06, 0x01, VISCA_MEMORY_SPEED, 0xFF])
        await self.__exec([0x81, 0x01, 0x04, 0x3F, 0x02, pos, 0xFF])

    async def recall(self, pos: int, focus: int):
        """Perform a recall with a certain position and focus value."""

        if self.recall_task is not None and not self.recall_task.done():
            self.recall_task.cancel()
            LOG.debug("Ongoing recall cancelled")

        async def recall_wrapper(pos_int, focus_int):
            LOG.debug(f"Executing recall of position {pos_int}...")
            # If AF has been enabled ephemerally (by cancelled recall), we can continue right away
            if not self.ephemeral_autofocus:
                af_mode = await self.inq_focus_af_mode()
                if af_mode == State.OFF:
                    LOG.debug("Enabling ephemeral AF...")
                    # Unlock focus ephemerally (activates AF) and set flag
                    self.ephemeral_autofocus = True
                    await self.set_focus_lock(State.OFF)
            # Recall camera position from memory
            await self.__memory_recall(pos_int)
            # If AF has been enabled ephemerally before, perform FL and clear flag
            if self.ephemeral_autofocus:
                LOG.debug("Disabling ephemeral AF...")
                await self.set_focus_lock(State.ON)
            # Apply saved focus for position
            await self.focus_direct(focus_int)

        self.recall_task = asyncio.create_task(recall_wrapper(pos, focus))
