"""Transparent WebSocket bridge; backend owns identity, presence and messages."""
import asyncio
from contextlib import suppress
from urllib.parse import urlsplit, urlunsplit
from channels.generic.websocket import AsyncWebsocketConsumer
from django.conf import settings
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake

class BackendSocket(AsyncWebsocketConsumer):
    async def connect(self):
        self.backend = None
        self.reader = None
        headers = dict(self.scope['headers'])
        destination = urlsplit(settings.BACKEND_URL)
        url = urlunsplit(('wss' if destination.scheme == 'https' else 'ws', destination.netloc,
                         self.scope['path'], self.scope.get('query_string', b'').decode('ascii'), ''))
        forwarded = {}
        for name in (b'cookie', b'user-agent'):
            if name in headers:
                forwarded[name.decode('ascii')] = headers[name].decode('latin1')
        origin = headers.get(b'origin')
        try:
            self.backend = await connect(url, additional_headers=forwarded,
                origin=origin.decode('latin1') if origin else None, proxy=None,
                open_timeout=5, close_timeout=3, max_size=2 ** 20)
        except (OSError, TimeoutError, InvalidHandshake):
            await self.close(code=4401)
            return
        await self.accept()
        self.reader = asyncio.create_task(self.read_backend())

    async def read_backend(self):
        code = 1000
        try:
            async for message in self.backend:
                if isinstance(message, str):
                    await self.send(text_data=message)
                else:
                    await self.send(bytes_data=message)
        except ConnectionClosed as error:
            code = error.rcvd.code if error.rcvd else 1011
        finally:
            if code in {1005, 1006, 1015}:
                code = 1011
            await self.close(code=code)

    async def receive(self, text_data=None, bytes_data=None):
        if self.backend is None:
            return
        try:
            await self.backend.send(text_data if text_data is not None else bytes_data)
        except ConnectionClosed:
            await self.close(code=1011)

    async def disconnect(self, close_code):
        if self.reader and self.reader is not asyncio.current_task():
            self.reader.cancel()
            with suppress(asyncio.CancelledError):
                await self.reader
        if self.backend:
            await self.backend.close()
