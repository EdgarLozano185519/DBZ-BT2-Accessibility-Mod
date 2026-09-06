"""Small dependency-free client for PCSX2's PINE IPC protocol."""

from __future__ import annotations

import socket
import struct
from dataclasses import dataclass


class PineError(RuntimeError):
    """Raised when PCSX2 rejects a PINE request or disconnects."""


@dataclass(frozen=True)
class GameInfo:
    emulator: str
    title: str
    serial: str
    crc: str
    game_version: str
    status: int


class PineClient:
    READ8 = 0
    READ16 = 1
    READ32 = 2
    READ64 = 3
    WRITE8 = 4
    WRITE16 = 5
    WRITE32 = 6
    WRITE64 = 7
    VERSION = 8
    SAVE_STATE = 9
    LOAD_STATE = 0x0A
    TITLE = 0x0B
    SERIAL = 0x0C
    CRC = 0x0D
    GAME_VERSION = 0x0E
    STATUS = 0x0F
    MAX_BATCH_COMMANDS = 4096
    MAX_ROUTINE_RANGE = 1024 * 1024

    def __init__(self, host: str = "127.0.0.1", port: int = 28011, timeout: float = 5.0):
        self._socket = socket.create_connection((host, port), timeout=timeout)
        self._socket.settimeout(timeout)

    def __enter__(self) -> "PineClient":
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        self.close()

    def close(self) -> None:
        self._socket.close()

    def _receive_exact(self, size: int) -> bytes:
        result = bytearray(size)
        view = memoryview(result)
        offset = 0
        while offset < size:
            count = self._socket.recv_into(view[offset:])
            if count == 0:
                raise PineError("PCSX2 disconnected during a PINE response")
            offset += count
        return bytes(result)

    def _request(self, commands: bytes) -> bytes:
        self._socket.sendall(struct.pack("<I", len(commands) + 4) + commands)
        response_size = struct.unpack("<I", self._receive_exact(4))[0]
        if response_size < 5:
            raise PineError(f"Invalid PINE response size: {response_size}")
        response = self._receive_exact(response_size - 4)
        if response[0] != 0:
            raise PineError("PCSX2 rejected the PINE request")
        return response[1:]

    def _string(self, opcode: int) -> str:
        response = self._request(bytes((opcode,)))
        size = struct.unpack_from("<I", response)[0]
        return response[4 : 4 + size].rstrip(b"\0").decode("utf-8", errors="replace")

    def info(self) -> GameInfo:
        return GameInfo(
            emulator=self._string(self.VERSION),
            title=self._string(self.TITLE),
            serial=self._string(self.SERIAL),
            crc=self._string(self.CRC),
            game_version=self._string(self.GAME_VERSION),
            status=self.status(),
        )

    def status(self) -> int:
        """Return only the VM state without the five string-info requests."""
        return struct.unpack("<I", self._request(bytes((self.STATUS,))))[0]

    def read8(self, address: int) -> int:
        return self._read_integer(self.READ8, "<B", address)

    def read16(self, address: int) -> int:
        return self._read_integer(self.READ16, "<H", address)

    def read32(self, address: int) -> int:
        return self._read_integer(self.READ32, "<I", address)

    def read32_many(self, addresses: list[int] | tuple[int, ...]) -> tuple[int, ...]:
        """Read several words in one PINE request.

        PCSX2 services a command batch together.  This matters for values that
        change every frame: issuing one socket request per address can otherwise
        produce a snapshot assembled from several different game frames.
        """
        if not addresses:
            return ()
        if len(addresses) > self.MAX_BATCH_COMMANDS:
            raise ValueError(
                f"A routine PINE batch is limited to {self.MAX_BATCH_COMMANDS} reads"
            )
        commands = bytearray(len(addresses) * 5)
        for index, address in enumerate(addresses):
            offset = index * 5
            commands[offset] = self.READ32
            struct.pack_into("<I", commands, offset + 1, address)
        response = self._request(commands)
        expected_size = len(addresses) * 4
        if len(response) != expected_size:
            raise PineError(
                f"Expected {expected_size} batched bytes but received {len(response)}"
            )
        return struct.unpack(f"<{len(addresses)}I", response)

    def read64(self, address: int) -> int:
        return self._read_integer(self.READ64, "<Q", address)

    def read_float(self, address: int) -> float:
        return struct.unpack("<f", struct.pack("<I", self.read32(address)))[0]

    def read_vector3(self, address: int) -> tuple[float, float, float]:
        return tuple(self.read_float(address + offset) for offset in (0, 4, 8))

    def read_vector3_many(
        self, addresses: list[int] | tuple[int, ...]
    ) -> tuple[tuple[float, float, float], ...]:
        """Read multiple three-float vectors from a single emulated frame."""
        word_addresses = tuple(
            address + offset for address in addresses for offset in (0, 4, 8)
        )
        words = self.read32_many(word_addresses)
        values = struct.unpack(
            f"<{len(words)}f", struct.pack(f"<{len(words)}I", *words)
        )
        return tuple(
            (values[index], values[index + 1], values[index + 2])
            for index in range(0, len(values), 3)
        )

    def _read_integer(self, opcode: int, format_string: str, address: int) -> int:
        command = bytes((opcode,)) + struct.pack("<I", address)
        return struct.unpack(format_string, self._request(command))[0]

    def write32(self, address: int, value: int) -> None:
        command = bytes((self.WRITE32,)) + struct.pack("<II", address, value)
        self._request(command)

    def write32_many_and_read32_many(
        self,
        writes: list[tuple[int, int]] | tuple[tuple[int, int], ...],
        read_addresses: list[int] | tuple[int, ...],
    ) -> tuple[int, ...]:
        """Apply a small write set and verify it within one PINE transaction."""
        command_count = len(writes) + len(read_addresses)
        if command_count > self.MAX_BATCH_COMMANDS:
            raise ValueError(
                f"A PINE transaction is limited to {self.MAX_BATCH_COMMANDS} commands"
            )
        commands = bytearray(len(writes) * 9 + len(read_addresses) * 5)
        offset = 0
        for address, value in writes:
            commands[offset] = self.WRITE32
            struct.pack_into("<II", commands, offset + 1, address, value)
            offset += 9
        for address in read_addresses:
            commands[offset] = self.READ32
            struct.pack_into("<I", commands, offset + 1, address)
            offset += 5
        response = self._request(commands)
        expected_size = len(read_addresses) * 4
        if len(response) != expected_size:
            raise PineError(
                f"Expected {expected_size} transactional bytes but received "
                f"{len(response)}"
            )
        if not read_addresses:
            return ()
        return struct.unpack(f"<{len(read_addresses)}I", response)

    def write_float(self, address: int, value: float) -> None:
        self.write32(address, struct.unpack("<I", struct.pack("<f", value))[0])

    def save_state(self, slot: int) -> None:
        self._state_command(self.SAVE_STATE, slot)

    def load_state(self, slot: int) -> None:
        self._state_command(self.LOAD_STATE, slot)

    def _state_command(self, opcode: int, slot: int) -> None:
        if not 0 <= slot <= 255:
            raise ValueError("savestate slot must be between 0 and 255")
        self._request(bytes((opcode, slot)))

    def read_aligned_range(
        self,
        address: int,
        size: int,
        reads_per_batch: int = 4096,
        *,
        allow_large: bool = False,
    ) -> bytes:
        """Read an eight-byte-aligned range using batched PINE READ64 commands."""
        if address % 8 or size % 8:
            raise ValueError("address and size must both be divisible by eight")
        if reads_per_batch < 1 or reads_per_batch > self.MAX_BATCH_COMMANDS:
            raise ValueError(
                f"reads_per_batch must be between 1 and {self.MAX_BATCH_COMMANDS}"
            )
        if size > self.MAX_ROUTINE_RANGE and not allow_large:
            raise ValueError(
                f"Refusing a {size}-byte routine PINE read; diagnostic callers "
                "must explicitly opt into large transfers"
            )

        output = bytearray(size)
        write_offset = 0
        end_address = address + size
        batch_byte_size = reads_per_batch * 8

        for batch_address in range(address, end_address, batch_byte_size):
            batch_size = min(batch_byte_size, end_address - batch_address)
            commands = bytearray((batch_size // 8) * 5)
            command_offset = 0
            for read_address in range(batch_address, batch_address + batch_size, 8):
                commands[command_offset] = self.READ64
                struct.pack_into("<I", commands, command_offset + 1, read_address)
                command_offset += 5
            response = self._request(commands)
            if len(response) != batch_size:
                raise PineError(f"Expected {batch_size} bytes but received {len(response)}")
            output[write_offset : write_offset + batch_size] = response
            write_offset += batch_size

        return bytes(output)
