"""Authenticated presence and live chat for the single-process campus prototype."""
import asyncio
from contextlib import suppress
from importlib import import_module
import json
import logging
import math
import time
from types import SimpleNamespace
from uuid import uuid4

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.conf import settings
from django.contrib.auth import get_user
from django.db import DatabaseError
from django.utils import timezone

from accounts.models import get_identity, needs_profile_setup
from .doors import DOORS, distance as door_distance, footprint as door_footprint
from .positions import DIRECTIONS, FLOOR_BOUNDS, get_position, save_position, validate_position


class CampusRoom:
    group = "campus.main"

    def __init__(self):
        self.players = {}
        self.doors = {door_id: False for door_id in DOORS}
        self.lock = asyncio.Lock()


room = CampusRoom()


class CampusConsumer(AsyncWebsocketConsumer):
    session_check_interval = 10
    idle_timeout = 60
    max_chat_length = 200
    chat_interval = 0.8
    position_interval = 5
    colors = {"#dfa34d", "#4e9b91", "#8a78bb", "#cb7773", "#648eb5"}
    directions = DIRECTIONS
    floor_bounds = FLOOR_BOUNDS

    async def connect(self):
        self.player_id = None
        self.guard_task = None
        self.position_dirty = False
        self.user = self.scope["user"]
        if not self.user.is_authenticated or not self.user.is_active:
            await self.close(code=4401)
            return
        if await database_sync_to_async(needs_profile_setup)(self.user):
            await self.close(code=4403)
            return
        self.session_key = self.scope["session"].session_key
        self.player_id = uuid4().hex
        self.last_seen = time.monotonic()
        self.last_move = 0
        self.last_chat = -math.inf
        self.last_door = -math.inf
        self.last_checkpoint = self.last_seen
        self.position_changed_at = None
        identity = await database_sync_to_async(get_identity)(self.user)
        position = await database_sync_to_async(get_position)(self.user)
        self.state = {
            "id": self.player_id, **identity, **position, "color": "#dfa34d", "moving": False,
        }
        async with room.lock:
            await self.channel_layer.group_add(room.group, self.channel_name)
            room.players[self.player_id] = self.state.copy()
            await self.accept()
            await self.send_packet({"type": "welcome", "selfId": self.player_id, "players": list(room.players.values()), "doors": room.doors.copy()})
            await self.broadcast({"type": "join", "player": self.state.copy()})
        self.guard_task = asyncio.create_task(self.check_session_loop())

    async def receive(self, text_data=None, bytes_data=None):
        if not self.player_id or self.player_id not in room.players:
            return
        if text_data is None or len(text_data) > 4096:
            await self.leave()
            await self.close(code=1009)
            return
        try:
            data = json.loads(text_data)
        except (ValueError, RecursionError):
            await self.leave()
            await self.close(code=1007)
            return
        if not isinstance(data, dict):
            return
        if data.get("type") == "chat":
            await self.receive_chat(data)
            return
        if data.get("type") == "door":
            await self.receive_door(data)
            return
        if data.get("type") == "ping":
            self.last_seen = time.monotonic()
            await self.send_packet({"type": "pong"})
            return
        if data.get("type") == "leave":
            # The final frame bypasses movement throttling and precedes socket close.
            await self.receive_movement(data, final=True)
            await self.leave()
            await self.close(code=1000)
            return
        if data.get("type") == "move":
            await self.receive_movement(data)

    async def receive_movement(self, data, final=False):
        floor = data.get("floor", self.state["floor"])
        position = validate_position({**data, "floor": floor})
        if (position is None or type(data.get("color")) is not str
                or data["color"] not in self.colors or type(data.get("moving")) is not bool):
            return
        now = time.monotonic()
        self.last_seen = now
        floor_changed = floor != self.state["floor"]
        if not final and not floor_changed and now - self.last_move < 0.045:
            return
        self.last_move = now
        if any(self.state[key] != value for key, value in position.items()):
            self.position_dirty = True
            self.position_changed_at = timezone.now()
        # Identity is always taken from the session, never from the message.
        self.state.update(**position, color=data["color"], moving=False if final else data["moving"])
        async with room.lock:
            if self.player_id in room.players:
                room.players[self.player_id] = self.state.copy()
                await self.broadcast({"type": "move", "player": self.state.copy()})
        await self.checkpoint(force=final or floor_changed)

    async def receive_door(self, data):
        door_id, opened = data.get("doorId"), data.get("open")
        if not isinstance(door_id, str) or door_id not in DOORS or type(opened) is not bool:
            return
        now = time.monotonic()
        if now - self.last_door < 0.15:
            await self.send_packet({"type": "door_error", "message": "잠시 후 문을 다시 눌러 주세요."})
            return
        self.last_door = self.last_seen = now
        if await self.current_identity() is None:
            await self.leave()
            await self.close(code=4401)
            return
        async with room.lock:
            if self.player_id not in room.players:
                return
            geometry = DOORS[door_id]
            current = room.doors[door_id]
            # Allow for the short interval between client movement reports.
            if (self.state["floor"] != "campus" or min(door_distance(door_footprint(geometry, state), self.state) for state in (False, current)) >= 50):
                await self.send_packet({"type": "door_error", "message": "유리문 가까이에서 조작해 주세요."})
                return
            payload = {"type": "door_state", "doorId": door_id, "open": opened}
            if current == opened:
                await self.send_packet(payload)
                return
            target = door_footprint(geometry, opened)
            if any(player["floor"] == "campus" and door_distance(target, player) < 6 for player in room.players.values()):
                await self.send_packet({"type": "door_error", "message": "문이 움직일 자리에 캐릭터가 있어요. 조금 비켜서 다시 눌러 주세요."})
                return
            room.doors[door_id] = opened
            await self.broadcast(payload)

    async def receive_chat(self, data):
        text = data.get("text")
        if not isinstance(text, str):
            await self.chat_error("메시지를 입력해 주세요.")
            return
        text = " ".join(text.split())
        try:
            text.encode("utf-8")
        except UnicodeEncodeError:
            await self.chat_error("메시지에 사용할 수 없는 문자가 있어요.")
            return
        if not text or len(text) > self.max_chat_length or any(ord(c) < 32 or ord(c) == 127 for c in text):
            await self.chat_error("메시지는 1~200자로 입력해 주세요.")
            return
        now = time.monotonic()
        if now - self.last_chat < self.chat_interval:
            await self.chat_error("잠시 후 다시 보내 주세요.")
            return
        # Re-check the session before publishing chat, including logout in another tab.
        identity = await self.current_identity()
        if identity is None:
            await self.leave()
            await self.close(code=4401)
            return
        self.last_seen = self.last_chat = now
        self.state.update(identity)
        async with room.lock:
            if self.player_id not in room.players:
                return
            room.players[self.player_id] = self.state.copy()
            await self.broadcast({"type": "chat", "message": {
                "id": uuid4().hex,
                "playerId": self.player_id,
                "nickname": identity["nickname"],
                "floor": self.state["floor"],
                "text": text,
                "sentAt": timezone.now().isoformat(),
            }})

    async def chat_error(self, message):
        await self.send_packet({"type": "chat_error", "message": message})

    async def send_packet(self, payload):
        await self.send(text_data=json.dumps(payload, ensure_ascii=False, allow_nan=False))

    async def broadcast(self, payload):
        await self.channel_layer.group_send(room.group, {
            "type": "presence.packet", "sender": self.player_id, "payload": payload,
        })

    async def presence_packet(self, event):
        if self.player_id in room.players and (event["sender"] != self.player_id or event["payload"]["type"] in {"chat", "door_state"}):
            await self.send_packet(event["payload"])

    @database_sync_to_async
    def current_identity(self):
        user = self.session_user()
        return get_identity(user) if user is not None else None

    def session_user(self):
        # A fresh session store catches logout/password changes in another tab.
        store = import_module(settings.SESSION_ENGINE).SessionStore(session_key=self.session_key)
        user = get_user(SimpleNamespace(session=store))
        if not user.is_authenticated or not user.is_active or user.pk != self.user.pk:
            return None
        return user

    @database_sync_to_async
    def store_position(self, position, observed_at):
        user = self.session_user()
        if user is not None:
            save_position(user, position, observed_at)

    async def checkpoint(self, force=False):
        if not self.position_dirty or (not force and time.monotonic() - self.last_checkpoint < self.position_interval):
            return
        self.last_checkpoint = time.monotonic()
        try:
            await self.store_position(self.state.copy(), self.position_changed_at)
        except DatabaseError:
            logging.getLogger(__name__).exception("Could not save the campus position")
        else:
            self.position_dirty = False

    async def check_session_loop(self):
        while True:
            await asyncio.sleep(min(self.session_check_interval, self.position_interval))
            await self.channel_layer.send(self.channel_name, {"type": "presence.check"})

    async def presence_check(self, event):
        if self.player_id not in room.players:
            return
        identity = await self.current_identity()
        if identity is None or time.monotonic() - self.last_seen > self.idle_timeout:
            await self.leave()
            await self.close(code=4401 if identity is None else 4408)
            return
        await self.checkpoint(force=True)
        if any(self.state[key] != value for key, value in identity.items()):
            self.state.update(identity)
            async with room.lock:
                room.players[self.player_id] = self.state.copy()
                await self.broadcast({"type": "move", "player": self.state.copy()})
            await self.send_packet({"type": "identity", "player": self.state.copy()})

    async def leave(self):
        await self.checkpoint(force=True)
        async with room.lock:
            if self.player_id and room.players.pop(self.player_id, None) is not None:
                await self.channel_layer.group_discard(room.group, self.channel_name)
                await self.broadcast({"type": "leave", "id": self.player_id})

    async def disconnect(self, close_code):
        if self.guard_task:
            self.guard_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.guard_task
        await self.leave()
