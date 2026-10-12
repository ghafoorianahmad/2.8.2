"""Fake-TLS against a local proxy that checks what mtprotoproxy/mtg check."""
from __future__ import annotations

import asyncio
import collections
import hashlib
import hmac
import logging
import os
import struct
import time

import pytest
from telethon.crypto import AESModeCTR

from app import faketls
from app.faketls import CCS, ConnectionTcpMTProxyFakeTLS, FakeTlsError, build_client_hello

KEY = bytes(range(16))
DOMAIN = b"www.example.com"
SECRET = "ee" + KEY.hex() + DOMAIN.hex()


def check_client_hello(hello: bytes, key: bytes) -> bytes:
    """Server-side validation (as in mtprotoproxy); returns the client digest."""
    assert hello[:11] == b"\x16\x03\x01\x02\x00\x01\x00\x01\xfc\x03\x03"
    assert hello[43] == 0x20                       # 32-byte session id
    zeroed = hello[:11] + bytes(32) + hello[43:]
    digest = hmac.new(key, zeroed, hashlib.sha256).digest()
    got = hello[11:43]
    assert got[:28] == digest[:28], "bad HMAC"
    stamp = int.from_bytes(got[28:32], "little") ^ int.from_bytes(digest[28:32], "little")
    assert abs(stamp - time.time()) < 120
    return got


def parse_sni(hello: bytes) -> bytes:
    pos = 5 + 4 + 2 + 32
    pos += 1 + hello[pos]                                         # session id
    pos += 2 + struct.unpack(">H", hello[pos:pos + 2])[0]         # ciphers
    pos += 1 + hello[pos]                                         # compression
    end = pos + 2 + struct.unpack(">H", hello[pos:pos + 2])[0]
    pos += 2
    assert end == len(hello)
    while pos < end:
        kind, length = struct.unpack(">HH", hello[pos:pos + 4])
        if kind == 0:
            data = hello[pos + 4:pos + 4 + length]
            return data[5:5 + struct.unpack(">H", data[3:5])[0]]
        pos += 4 + length
    raise AssertionError("no SNI")


def server_reply(key: bytes, client_digest: bytes, *, sign: bool = True) -> bytes:
    body = b"\x02\x00\x00\x76\x03\x03" + bytes(32) + b"\x20" + os.urandom(32) + os.urandom(53)
    hello = b"\x16\x03\x03" + struct.pack(">H", len(body)) + body
    cert = os.urandom(1200)
    reply = bytearray(hello + CCS + b"\x17\x03\x03" + struct.pack(">H", len(cert)) + cert)
    digest = hmac.new(key if sign else b"x" * 16, client_digest + bytes(reply), hashlib.sha256).digest()
    reply[11:43] = digest
    return bytes(reply)


def test_client_hello_is_valid_tls_and_signed():
    hello = build_client_hello(KEY, DOMAIN)
    assert len(hello) == 517
    check_client_hello(hello, KEY)
    assert parse_sni(hello) == DOMAIN
    # every hello is different (random session id / key share / time)
    assert build_client_hello(KEY, DOMAIN)[43:] != hello[43:]


def test_long_domain_is_refused():
    with pytest.raises(ValueError):
        build_client_hello(KEY, b"a" * 400)


async def _serve(handler):
    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


def test_full_connection_sends_obfuscated2_inside_tls():
    seen = {}

    async def handler(reader, writer):
        hello = await reader.readexactly(517)
        seen["sni"] = parse_sni(hello)
        writer.write(server_reply(KEY, check_client_hello(hello, KEY)))
        await writer.drain()
        assert await reader.readexactly(6) == CCS
        tls = faketls.TlsReader(reader)
        header = await tls.readexactly(64)
        enc_key = hashlib.sha256(header[8:40] + KEY).digest()
        plain = AESModeCTR(enc_key, header[40:56]).encrypt(header)
        seen["tag"] = plain[56:60]
        seen["dc"] = struct.unpack("<h", plain[60:62])[0]
        await asyncio.sleep(0.2)
        writer.close()

    async def scenario():
        server, port = await _serve(handler)
        loggers = collections.defaultdict(lambda: logging.getLogger("test"))
        conn = ConnectionTcpMTProxyFakeTLS("149.154.167.51", 443, 2, loggers=loggers,
                                           proxy=("127.0.0.1", port, SECRET))
        await conn.connect(timeout=5)
        await asyncio.sleep(0.1)
        await conn.disconnect()
        server.close()
        await server.wait_closed()
    asyncio.run(scenario())
    assert seen == {"sni": DOMAIN, "tag": b"\xdd\xdd\xdd\xdd", "dc": 2}


def test_wrong_server_signature_is_rejected():
    async def handler(reader, writer):
        hello = await reader.readexactly(517)
        writer.write(server_reply(KEY, hello[11:43], sign=False))
        await writer.drain()
        await asyncio.sleep(0.2)
        writer.close()

    async def scenario():
        server, port = await _serve(handler)
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        try:
            with pytest.raises(FakeTlsError):
                await faketls.handshake(reader, writer, KEY, DOMAIN)
        finally:
            writer.close()
            server.close()
            await server.wait_closed()
    asyncio.run(scenario())


def test_non_tls_answer_is_rejected():
    async def handler(reader, writer):
        await reader.readexactly(517)
        writer.write(b"HTTP/1.1 400 Bad Request\r\n\r\n")
        await writer.drain()
        writer.close()

    async def scenario():
        server, port = await _serve(handler)
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        try:
            with pytest.raises(FakeTlsError):
                await faketls.handshake(reader, writer, KEY, DOMAIN)
        finally:
            writer.close()
            server.close()
            await server.wait_closed()
    asyncio.run(scenario())


def test_writer_splits_records_and_reader_reassembles():
    class Sink:
        def __init__(self):
            self.data = bytearray()

        def write(self, b):
            self.data += b

    sink = Sink()
    w = faketls.TlsWriter(sink)
    payload = os.urandom(40000)
    w.write(payload)
    assert sink.data.startswith(CCS)

    async def read_back():
        r = asyncio.StreamReader()
        r.feed_data(bytes(sink.data[len(CCS):]))
        r.feed_eof()
        tls = faketls.TlsReader(r)
        return await tls.readexactly(10) + await tls.readexactly(len(payload) - 10)
    assert asyncio.run(read_back()) == payload


def test_only_ee_secrets_are_accepted():
    loggers = collections.defaultdict(lambda: logging.getLogger("test"))
    with pytest.raises(ValueError):
        ConnectionTcpMTProxyFakeTLS("1.1.1.1", 443, 2, loggers=loggers,
                                    proxy=("h", 1, "dd" + KEY.hex()))
