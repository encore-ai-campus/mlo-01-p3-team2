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
from accounts.session_policy import check_session
from eventing.events import ensure_platform_session, record_chat, record_floor_transfer, touch_platform_session
from raffle import live as raffle_live, service as raffle_service
from raffle import survey as raffle_survey
from . import session_registry
from .motion import MotionController, ControlError, geometry
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
        self.motion_task = None
        self.controller = None
        self.control_lock = asyncio.Lock()
        self.server_control = not getattr(settings, "CAMPUS_TEST_LEGACY_MOVEMENT", False) or b"control=server" in self.scope.get("query_string", b"")
        self.session_group = None
        self.policy_status = None
        self.last_activity_write = -math.inf
        self.position_dirty = False
        self.pending_floor_transfer = None
        self.user = self.scope["user"]
        if not self.user.is_authenticated or not self.user.is_active:
            await self.close(code=4401)
            return
        if await database_sync_to_async(needs_profile_setup)(self.user):
            await self.close(code=4403)
            return
        self.session_key = self.scope["session"].session_key
        self.policy_status = await database_sync_to_async(check_session)(self.session_key)
        if not self.policy_status["authenticated"]:
            await self.close(code=4401)
            return
        # check_session may have updated legacy policy fields; do not overwrite
        # them with the session snapshot already read by AuthMiddlewareStack.
        fresh_session = import_module(settings.SESSION_ENGINE).SessionStore(session_key=self.session_key)
        self.platform_session_uuid = await database_sync_to_async(ensure_platform_session)(
            self.user, fresh_session
        )
        self.session_group = session_registry.session_group(self.session_key)
        self.player_id = uuid4().hex
        self.last_seen = time.monotonic()
        self.last_move = 0
        self.last_chat = -math.inf
        self.last_door = -math.inf
        self.last_survey = -math.inf
        self.last_checkpoint = self.last_seen
        self.position_changed_at = None
        identity = await database_sync_to_async(get_identity)(self.user)
        position = await database_sync_to_async(get_position)(self.user)
        self.state = {
            "id": self.player_id, **identity, **position, "color": "#dfa34d", "moving": False,
        }
        if self.server_control:
            self.controller = MotionController(position, room.doors)
            corrected = self.controller.pose
            self.position_dirty = any(corrected[key] != position[key] for key in ("x", "y", "floor", "dir"))
            if self.position_dirty:
                self.position_changed_at = timezone.now()
            self.state.update(corrected, color=geometry()["avatarColors"].get(identity.get("avatar"), "#dfa34d"))
        raffle_live.bind_socket_loop(self.channel_layer)
        async with room.lock:
            await self.channel_layer.group_add(room.group, self.channel_name)
            await self.channel_layer.group_add(self.session_group, self.channel_name)
            # Subscribe before the final check so a login replacing this key
            # during the handshake cannot leave an unnoticed stale socket.
            if await self.current_identity() is None:
                await self.channel_layer.group_discard(room.group, self.channel_name)
                await self.channel_layer.group_discard(self.session_group, self.channel_name)
                await self.close(code=4401)
                return
            session_registry.register(self.player_id, self.session_key, self.user.pk)
            room.players[self.player_id] = self.state.copy()
            await self.accept()
            raffle = await database_sync_to_async(raffle_service.snapshot)(self.user)
            await self.send_packet({"type": "welcome", "selfId": self.player_id, "players": list(room.players.values()), "doors": room.doors.copy(), "session": self.policy_status, "raffle": raffle, "serverControl": self.server_control})
            await self.broadcast({"type": "join", "player": self.state.copy()})
        self.guard_task = asyncio.create_task(self.check_session_loop())
        if self.server_control:
            await self.send_control_state()
            self.motion_task = asyncio.create_task(self.motion_loop())

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
        if timezone.now().timestamp() * 1000 >= self.policy_status.get("expiresAt", 0):
            if await self.current_identity() is None:
                await self.session_expired({"reason": self.policy_status.get("reason", "signed_out")})
                return
        if data.get("type") == "input" and self.server_control:
            try:
                self.controller.input(data.get("keys"))
                self.last_seen = time.monotonic()
            except ControlError as error:
                await self.send_packet({"type": "control_error", "message": str(error)})
            return
        if data.get("type") == "control" and self.server_control:
            await self.receive_control(data)
            return
        if data.get("type") == "chat":
            await self.receive_chat(data)
            return
        if data.get("type") == "door":
            await self.receive_door(data)
            return
        if data.get("type") == "raffle_enter":
            await self.receive_raffle(data)
            return
        if data.get("type") == "ping":
            self.last_seen = time.monotonic()
            await database_sync_to_async(touch_platform_session)(self.platform_session_uuid)
            await self.send_packet({"type": "pong"})
            return
        if data.get("type") == "leave":
            # The final frame bypasses movement throttling and precedes socket close.
            if self.server_control:
                await self.receive_movement({**self.controller.pose, "color": self.state["color"]}, final=True, authoritative=True)
            else:
                await self.receive_movement(data, final=True)
            await self.leave()
            await self.close(code=1000)
            return
        if data.get("type") == "move":
            if self.server_control:
                await self.send_packet({"type": "control_error", "message": "좌표 대신 이동 키 입력을 보내 주세요."})
            else:
                await self.receive_movement(data)

    async def receive_movement(self, data, final=False, authoritative=False):
        floor = data.get("floor", self.state["floor"])
        position = validate_position({**data, "floor": floor})
        if (position is None or type(data.get("color")) is not str
                or data["color"] not in self.colors or type(data.get("moving")) is not bool):
            return
        now = time.monotonic()
        if not authoritative:
            self.last_seen = now
        previous_floor = self.state["floor"]
        floor_changed = floor != previous_floor
        publish = not authoritative or final or floor_changed or now - self.last_move >= 0.1
        if not authoritative and not final and not floor_changed and now - self.last_move < 0.045:
            return
        if publish:
            self.last_move = now
        changed = any(self.state[key] != value for key, value in position.items())
        if changed:
            self.position_dirty = True
            self.position_changed_at = timezone.now()
        if floor_changed:
            self.pending_floor_transfer = (previous_floor, floor)
        # Identity is always taken from the session, never from the message.
        self.state.update(**position, color=data["color"], moving=False if final else data["moving"])
        session_registry.update(self.player_id, self.state, self.position_changed_at)
        async with room.lock:
            if self.player_id in room.players:
                room.players[self.player_id] = self.state.copy()
                if publish:
                    await self.broadcast({"type": "move", "player": self.state.copy()})
        await self.checkpoint(force=final or floor_changed)
        if changed and not final and publish:
            await self.touch_activity()

    async def send_control_state(self):
        packet = self.controller.snapshot(room.doors)
        packet["main"] = {**self.state, **packet["main"]}
        if packet["interior"]:
            packet["interior"]["actor"].update(avatar=self.state.get("avatar", "male-1"), color=self.state["color"])
        await self.send_packet({"type": "control_state", "state": packet})

    async def motion_loop(self):
        previous = time.monotonic()
        try:
            while self.player_id in room.players:
                await asyncio.sleep(1 / 30)
                now = time.monotonic()
                seconds = now - previous
                previous = now
                async with self.control_lock:
                    if self.player_id not in room.players:
                        return
                    events = self.controller.tick(seconds, room.doors, now)
                    await self.receive_movement({**self.controller.pose, "color": self.state["color"]}, authoritative=True)
                    if self.controller.interior and self.controller.interior["actor"]["moving"]:
                        await self.touch_activity()
                    await self.send_control_state()
                    for event in events:
                        await self.send_packet({"type": "control_event", "event": event})
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.getLogger(__name__).exception("Campus movement calculation failed")
            await self.close(code=1011)

    async def receive_control(self, data):
        request_id = data.get("requestId")
        action = data.get("action")
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 64 or not isinstance(action, str):
            return
        arguments = data.get("data", {})
        if not isinstance(arguments, dict):
            return
        if await self.current_identity() is None:
            await self.session_expired({"reason": self.policy_status.get("reason", "signed_out")})
            return
        self.last_seen = time.monotonic()
        async with self.control_lock:
            try:
                if action == "navigate":
                    result = await asyncio.to_thread(self.controller.command, action, arguments, room.doors.copy())
                else:
                    result = self.controller.command(action, arguments, room.doors)
                await self.receive_movement({**self.controller.pose, "color": self.state["color"]}, authoritative=True)
                await self.send_control_state()
                await self.send_packet({"type": "control_result", "requestId": request_id, "result": result})
                await self.touch_activity()
            except ControlError as error:
                await self.send_packet({"type": "control_result", "requestId": request_id, "error": str(error)})

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
            await self.session_expired({"reason": self.policy_status.get("reason", "signed_out")})
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
        await self.touch_activity()

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
            await self.session_expired({"reason": self.policy_status.get("reason", "signed_out")})
            return
        if self.player_id not in room.players:
            return
        try:
            message_id = await database_sync_to_async(record_chat)(
                self.user, self.platform_session_uuid, text, self.state["floor"]
            )
        except DatabaseError:
            logging.getLogger(__name__).exception("Could not store accepted chat message")
            await self.chat_error("메시지를 저장하지 못했어요. 잠시 후 다시 보내 주세요.")
            return
        self.last_seen = self.last_chat = now
        self.state.update(identity)
        async with room.lock:
            if self.player_id not in room.players:
                return
            room.players[self.player_id] = self.state.copy()
            await self.broadcast({"type": "chat", "message": {
                "id": message_id,
                "playerId": self.player_id,
                "nickname": identity["nickname"],
                "floor": self.state["floor"],
                "text": text,
                "sentAt": timezone.now().isoformat(),
            }})
        await self.touch_activity()

    async def receive_raffle(self, data):
        # The authenticated socket supplies the real account and last reported
        # position. This only issues a survey code; it never registers an entry.
        if await self.current_identity() is None:
            await self.session_expired({"reason": self.policy_status.get("reason", "signed_out")})
            return
        now = time.monotonic()
        if now - self.last_survey < .8:
            await self.send_packet({"type": "raffle_error", "message": "잠시 후 다시 눌러 주세요."})
            return
        self.last_survey = self.last_seen = now
        try:
            event_id = data.get("eventId")
            if not isinstance(event_id, str) or len(event_id) != 36:
                raise raffle_service.RaffleError("대상 이벤트를 확인해 주세요.", 400)
            url = await database_sync_to_async(raffle_survey.begin)(self.user, self.state.copy(), event_id)
            state = await database_sync_to_async(raffle_service.snapshot)(self.user)
            await self.send_packet({"type": "raffle_survey", "eventId": event_id, "url": url, "state": state})
            await self.touch_activity()
        except raffle_service.RaffleError as error:
            await self.send_packet({"type": "raffle_error", "message": error.message})
        except DatabaseError:
            await self.send_packet({"type": "raffle_error", "message": "설문 참여 정보를 저장하지 못했어요. 잠시 후 다시 시도해 주세요."})

    async def raffle_changed(self, event):
        if self.player_id in room.players:
            state = await database_sync_to_async(raffle_service.snapshot)(self.user)
            await self.send_packet({"type": "raffle_state", "state": state})

    async def touch_activity(self):
        now = time.monotonic()
        if now - self.last_activity_write >= settings.CAMPUS_SESSION_ACTIVITY_WRITE_INTERVAL_SECONDS:
            self.last_activity_write = now
            state = await database_sync_to_async(check_session)(self.session_key, touch=True)
            if state.get("reason") != "retry":
                self.policy_status = state

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
        state = check_session(self.session_key)
        if state.get("reason") != "retry":
            self.policy_status = state
        if not state["authenticated"] and state.get("reason") != "retry":
            return None
        store = import_module(settings.SESSION_ENGINE).SessionStore(session_key=self.session_key)
        user = get_user(SimpleNamespace(session=store))
        if not user.is_authenticated or not user.is_active or user.pk != self.user.pk:
            return None
        return user

    @database_sync_to_async
    def store_position(self, position, observed_at, transfer_from=None):
        user = self.session_user()
        if user is not None:
            if transfer_from:
                return record_floor_transfer(
                    user, self.platform_session_uuid, transfer_from, position["floor"], position, observed_at
                )
            return save_position(user, position, observed_at, session_uuid=self.platform_session_uuid)

    async def checkpoint(self, force=False):
        if not self.position_dirty or (not force and time.monotonic() - self.last_checkpoint < self.position_interval):
            return
        self.last_checkpoint = time.monotonic()
        observed_at = self.position_changed_at
        transfer = self.pending_floor_transfer
        transfer_from = transfer[0] if transfer else None
        try:
            await self.store_position(self.state.copy(), observed_at, transfer_from)
        except DatabaseError:
            logging.getLogger(__name__).exception("Could not save the campus position")
        else:
            # A newer frame may arrive while the database write is awaiting.
            if self.position_changed_at == observed_at:
                self.position_dirty = False
            if self.pending_floor_transfer == transfer:
                self.pending_floor_transfer = None

    async def check_session_loop(self):
        while True:
            await asyncio.sleep(min(self.session_check_interval, self.position_interval))
            await self.channel_layer.send(self.channel_name, {"type": "presence.check"})

    async def presence_check(self, event):
        if self.player_id not in room.players:
            return
        identity = await self.current_identity()
        if identity is None:
            await self.session_expired({"reason": self.policy_status.get("reason", "signed_out")})
            return
        if time.monotonic() - self.last_seen > self.idle_timeout:
            await self.leave()
            await self.close(code=4408)
            return
        await self.checkpoint()
        if any(self.state[key] != value for key, value in identity.items()):
            self.state.update(identity)
            async with room.lock:
                room.players[self.player_id] = self.state.copy()
                await self.broadcast({"type": "move", "player": self.state.copy()})
            await self.send_packet({"type": "identity", "player": self.state.copy()})

    async def leave(self):
        await self.checkpoint(force=True)
        session_registry.unregister(self.player_id)
        if self.session_group:
            await self.channel_layer.group_discard(self.session_group, self.channel_name)
        async with room.lock:
            if self.player_id and room.players.pop(self.player_id, None) is not None:
                await self.channel_layer.group_discard(room.group, self.channel_name)
                await self.broadcast({"type": "leave", "id": self.player_id})

    async def session_expired(self, event):
        if self.player_id not in room.players:
            return
        reason = event.get("reason", "signed_out")
        if reason in {"idle", "maximum", "invalid", "replaced"}:
            await self.send_packet({"type": "session_expired", "reason": reason})
        await self.leave()
        await self.close(code=4401)

    async def disconnect(self, close_code):
        if self.motion_task:
            self.motion_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.motion_task
        if self.guard_task:
            self.guard_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.guard_task
        await self.leave()
