"""Fake-TLS ("ee" secret) MTProto proxy connection for Telethon.

Telethon 1.x strips the ``ee`` prefix and the domain from a secret and then
talks plain obfuscated2, which a fake-TLS proxy rejects. Most proxies in Iran
are fake-TLS, so this module adds the missing layer (the protocol of tdlib /
mtprotoproxy / mtg):

1. client -> proxy: a 517-byte TLS 1.3 ClientHello whose SNI is the secret's
   domain and whose 32-byte "random" is HMAC-SHA256(key, hello with zero
   random), the last 4 bytes XORed with the Unix time;
2. proxy -> client: ServerHello + ChangeCipherSpec + one ApplicationData
   record; its "random" is HMAC-SHA256(key, client random + reply with zero
   random), which we verify (a wrong proxy or a censor's middlebox fails here);
3. client sends ChangeCipherSpec, then everything (the usual obfuscated2 header
   and packets, randomized-intermediate codec) inside ApplicationData records.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import struct
import time

from telethon.network.connection.tcpmtproxy import ConnectionTcpMTProxyRandomizedIntermediate

HELLO_LEN = 517
RECORD_MAX = 16384
CCS = b"\x14\x03\x03\x00\x01\x01"
_CIPHERS = bytes.fromhex(
    "130113021303c02bc02fc02cc030cca9cca8c013c014009c009d002f0035")
_SIG_ALGS = bytes.fromhex("04030804040105030805050108060601")


class FakeTlsError(ConnectionError):
    pass


def _ext(kind: int, data: bytes) -> bytes:
    return struct.pack(">HH", kind, len(data)) + data


def build_client_hello(key: bytes, domain: bytes, *, now: int | None = None,
                       session_id: bytes | None = None, key_share: bytes | None = None) -> bytes:
    """The signed ClientHello record (``HELLO_LEN`` bytes)."""
    if len(key) != 16:
        raise ValueError("fake-TLS key must be 16 bytes")
    session_id = session_id if session_id is not None else os.urandom(32)
    key_share = key_share if key_share is not None else os.urandom(32)
    sni = struct.pack(">HBH", len(domain) + 3, 0, len(domain)) + domain
    exts = b"".join((
        _ext(0x0000, sni),
        _ext(0x0017, b""),                                   # extended master secret
        _ext(0xFF01, b"\x00"),                               # renegotiation info
        _ext(0x000A, bytes.fromhex("0008001d001700180019")),  # supported groups
        _ext(0x000B, b"\x01\x00"),                           # ec point formats
        _ext(0x0023, b""),                                   # session ticket
        _ext(0x0010, b"\x00\x0c\x02h2\x08http/1.1"),         # ALPN
        _ext(0x0005, b"\x01\x00\x00\x00\x00"),               # status request
        _ext(0x000D, struct.pack(">H", len(_SIG_ALGS)) + _SIG_ALGS),
        _ext(0x0012, b""),                                   # signed cert timestamps
        _ext(0x0033, b"\x00\x24\x00\x1d\x00\x20" + key_share),  # key share x25519
        _ext(0x002D, b"\x01\x01"),                           # psk modes
        _ext(0x002B, b"\x06\x03\x04\x03\x03\x03\x02"),       # supported versions
        _ext(0x001B, b"\x02\x00\x02"),                       # compress certificate
    ))
    head = (b"\x03\x03" + bytes(32) + b"\x20" + session_id
            + struct.pack(">H", len(_CIPHERS)) + _CIPHERS + b"\x01\x00")
    body_len = HELLO_LEN - 9                      # record header 5 + handshake header 4
    pad = body_len - len(head) - 2 - len(exts) - 4
    if pad < 0:
        raise ValueError("fake-TLS domain is too long")
    exts += _ext(0x0015, bytes(pad))              # padding
    body = head + struct.pack(">H", len(exts)) + exts
    handshake = b"\x01" + len(body).to_bytes(3, "big") + body
    hello = bytearray(b"\x16\x03\x01" + struct.pack(">H", len(handshake)) + handshake)
    assert len(hello) == HELLO_LEN
    digest = hmac.new(key, bytes(hello), hashlib.sha256).digest()
    stamp = int(time.time()) if now is None else now
    tail = (int.from_bytes(digest[28:32], "little") ^ stamp) & 0xFFFFFFFF
    hello[11:43] = digest[:28] + tail.to_bytes(4, "little")
    return bytes(hello)


async def _read_record(reader) -> tuple[int, bytes, bytes]:
    header = await reader.readexactly(5)
    if header[1:3] != b"\x03\x03":
        raise FakeTlsError("the proxy did not answer with TLS")
    length = struct.unpack(">H", header[3:5])[0]
    if length > RECORD_MAX + 256:
        raise FakeTlsError("TLS record too long")
    return header[0], header, await reader.readexactly(length)


async def handshake(reader, writer, key: bytes, domain: bytes) -> None:
    hello = build_client_hello(key, domain)
    writer.write(hello)
    await writer.drain()
    reply = bytearray()
    kind, header, payload = await _read_record(reader)
    if kind != 0x16:
        raise FakeTlsError("the proxy did not send a ServerHello")
    reply += header + payload
    while True:
        kind, header, payload = await _read_record(reader)
        reply += header + payload
        if kind == 0x17:
            break
        if kind != 0x14:
            raise FakeTlsError("unexpected TLS record in the proxy's hello")
    if len(reply) < 43:
        raise FakeTlsError("ServerHello too short")
    got = bytes(reply[11:43])
    reply[11:43] = bytes(32)
    want = hmac.new(key, hello[11:43] + bytes(reply), hashlib.sha256).digest()
    if not hmac.compare_digest(got, want):
        raise FakeTlsError("the proxy's TLS answer is not signed with this secret")


class TlsReader:
    """``readexactly`` over the payloads of incoming ApplicationData records."""

    def __init__(self, reader):
        self._reader = reader
        self._buf = bytearray()

    async def readexactly(self, n: int) -> bytes:
        while len(self._buf) < n:
            kind, _, payload = await _read_record(self._reader)
            if kind == 0x17:
                self._buf += payload
            elif kind == 0x15:
                raise FakeTlsError("the proxy sent a TLS alert")
            elif kind != 0x14:
                raise FakeTlsError("unexpected TLS record")
        out = bytes(self._buf[:n])
        del self._buf[:n]
        return out

    def at_eof(self) -> bool:
        return not self._buf and self._reader.at_eof()

    def __getattr__(self, name):          # _wait_for_data and friends
        return getattr(self._reader, name)


class TlsWriter:
    """Wraps outgoing bytes in ApplicationData records (CCS before the first)."""

    def __init__(self, writer):
        self._writer = writer
        self._sent_ccs = False

    def write(self, data: bytes) -> None:
        if not self._sent_ccs:
            self._writer.write(CCS)
            self._sent_ccs = True
        for start in range(0, len(data), RECORD_MAX):
            chunk = data[start:start + RECORD_MAX]
            self._writer.write(b"\x17\x03\x03" + struct.pack(">H", len(chunk)) + chunk)

    def __getattr__(self, name):          # drain, close, wait_closed, ...
        return getattr(self._writer, name)


class ConnectionTcpMTProxyFakeTLS(ConnectionTcpMTProxyRandomizedIntermediate):
    """Use as ``connection=`` with ``proxy=(host, port, 'ee…hex secret')``."""

    def __init__(self, ip, port, dc_id, *, loggers, proxy=None, local_addr=None):
        full = bytes.fromhex(proxy[2])
        if full[:1] != b"\xee" or len(full) < 18:
            raise ValueError("not a fake-TLS (ee) secret")
        self._tls_domain = full[17:]
        super().__init__(ip, port, dc_id, loggers=loggers, proxy=(proxy[0], proxy[1], full[1:17].hex()))

    async def _connect(self, timeout=None, ssl=None):
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host=self._ip, port=self._port), timeout=timeout)
        try:
            await asyncio.wait_for(handshake(reader, writer, self._secret, self._tls_domain),
                                   timeout=timeout)
        except BaseException:
            writer.close()
            raise
        self._reader = TlsReader(reader)
        self._writer = TlsWriter(writer)
        self._codec = self.packet_codec(self)
        self._init_conn()
        await self._writer.drain()
