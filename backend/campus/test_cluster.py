"""여러 프로세스 사본(계획 M3): 다른 프로세스의 입장·이동·목록·퇴장·끊김을 같은 결과로 반영한다."""
from unittest.mock import AsyncMock, patch

from django.test import SimpleTestCase

from . import cluster, consumers


def message(kind, seq, proc="other", **fields):
    return {"type": "cluster.message", "kind": kind, "proc": proc, "seq": seq, **fields}


def entry(player_id, x=100, **state):
    return {"id": player_id, "state": {"id": player_id, "floor": "campus", "x": x, "y": 50, "nickname": player_id, **state},
            "channel": "specific." + player_id, "session": "s-" + player_id}


class ClusterMirrorTests(SimpleTestCase):
    def setUp(self):
        self.c = cluster.Cluster()

    def test_join_moves_and_leave_reach_local_sockets_once(self):
        self.assertEqual(self.c.apply(message("join", 1, entry=entry("a"))), [{"type": "join", "player": entry("a")["state"]}])
        self.assertEqual(self.c.apply(message("join", 2, entry=entry("a"))), [])  # 이미 안다: 다시 알리지 않는다
        moved = {**entry("a", x=140)["state"]}
        self.assertEqual(self.c.apply(message("moves", 3, players=[moved, entry("unknown")["state"]])), [])
        self.assertEqual(self.c.remote["a"]["state"]["x"], 140)
        self.assertEqual(list(self.c.remote_moves), ["a"])  # 모르는 사람의 이동은 사본을 만들지 않는다
        self.assertEqual(self.c.apply(message("leave", 4, id="a")), [{"type": "leave", "id": "a"}])
        self.assertEqual(self.c.remote, {})
        self.assertEqual(self.c.remote_moves, {})

    def test_own_messages_are_ignored(self):
        self.assertEqual(self.c.apply(message("join", 1, proc=cluster.PROC, entry=entry("me"))), [])
        self.assertEqual(self.c.remote, {})

    def test_snapshot_adds_missing_people_and_drops_departed_ones_of_that_process(self):
        self.c.apply(message("join", 1, entry=entry("a")))
        self.c.apply(message("join", 2, proc="third", entry=entry("z")))
        out = self.c.apply(message("snapshot", 3, players=[entry("b")]))
        self.assertEqual(sorted(p["type"] for p in out), ["join", "leave"])
        self.assertEqual(set(self.c.remote), {"b", "z"})  # 다른 프로세스(third)의 사람은 그대로다

    def test_late_snapshot_or_join_cannot_resurrect_someone_who_left(self):
        self.c.apply(message("join", 1, entry=entry("a")))
        self.c.apply(message("leave", 5, id="a"))
        self.assertEqual(self.c.apply(message("snapshot", 4, players=[entry("a")])), [])  # 떠나기 전에 만든 목록이 늦게 왔다
        self.assertEqual(self.c.apply(message("join", 3, entry=entry("a"))), [])
        self.assertNotIn("a", self.c.remote)
        self.assertTrue(self.c.apply(message("join", 6, entry=entry("a"))))  # 다시 들어온 것은 받는다

    def test_silent_process_is_forgotten_after_three_seconds(self):
        self.c.apply(message("join", 1, entry=entry("a")))
        heard = self.c.heard["other"]
        self.assertEqual(self.c.expire(now=heard + cluster.SILENT_SECONDS - .1), [])
        self.assertEqual(self.c.expire(now=heard + cluster.SILENT_SECONDS + .1), [{"type": "leave", "id": "a"}])
        self.assertEqual(self.c.remote, {})

    def test_published_entry_carries_routing_fields_but_peers_only_see_the_state(self):
        class Socket:
            player_id, channel_name, session_key = "me", "specific.me", "key"
            state = {"id": "me", "x": 1}
            seen_by_peers = {"id": "me", "x": 2}
        row = cluster.Cluster.entry(Socket())
        self.assertEqual(row["state"], {"id": "me", "x": 2})
        self.assertEqual(row["session"], cluster.session_hash("key"))
        self.c.apply(message("join", 1, entry={**row, "id": "me2", "state": {**row["state"], "id": "me2"}}))
        self.assertNotIn("channel", self.c.remote["me2"]["state"])  # 브라우저로 가는 상태에는 채널·세션이 없다


class EffectTests(SimpleTestCase):
    """찌르기·점프·채팅(계획 M8): 이 프로세스 소켓에는 바로, 다른 프로세스에는 0.1초 묶음에 한 번."""

    async def test_effects_ride_the_moves_batch_once(self):
        c = cluster.Cluster()
        c.send = AsyncMock()
        effect = {"payload": {"type": "jump"}, "to": None, "near": ["campus", 1, 2, 3]}
        c.effects.append(effect)
        with patch.object(cluster, "enabled", return_value=True):
            await c.moved([])
            await c.moved([])  # 보낼 것이 없으면 보내지 않는다
        c.send.assert_awaited_once_with("moves", players=[], effects=[effect])
        c.apply(message("moves", 1, players=[], effects=[effect]))
        self.assertEqual(c.effects_in, [effect])

    async def test_local_sockets_get_it_now_and_other_processes_only_when_someone_there_receives_it(self):
        room = consumers.CampusRoom()
        room.players = {"me": {"floor": "campus", "x": 0, "y": 0}, "peer": {"floor": "campus", "x": 10, "y": 0}}
        room.sockets = {key: AsyncMock() for key in room.players}
        room.cluster.remote = {"there": {"state": {"floor": "campus", "x": 5, "y": 0}, "proc": "other"}}
        with patch.object(cluster, "enabled", return_value=True):
            await consumers.share_effect(room, {"type": "poke_state"}, to={"me", "there"})
            await consumers.share_effect(room, {"type": "poke_state"}, to={"peer"})  # 모두 이 프로세스에 있다
            await consumers.share_effect(room, {"type": "chat"})
        self.assertEqual((room.sockets["me"].send.await_count, room.sockets["peer"].send.await_count), (2, 2))
        self.assertEqual([effect["to"] for effect in room.cluster.effects], [["there"], None])

    async def test_effects_from_other_processes_reach_only_their_recipients(self):
        room = consumers.CampusRoom()
        room.players = {"me": {"floor": "campus", "x": 0, "y": 0}, "roof": {"floor": "rooftop", "x": 0, "y": 0}}
        room.sockets = {key: AsyncMock() for key in room.players}
        room.cluster.effects_in = [{"payload": {"type": "jump"}, "to": None, "near": ["campus", 0, 0, 100]},
                                   {"payload": {"type": "poke_hit"}, "to": ["roof", "elsewhere"], "near": None}]
        await consumers.send_to_sockets(room, [])
        self.assertEqual([call.kwargs["text_data"] for call in room.sockets["me"].send.await_args_list], ['{"type": "jump"}'])
        self.assertEqual([call.kwargs["text_data"] for call in room.sockets["roof"].send.await_args_list], ['{"type": "poke_hit"}'])
        self.assertEqual(room.cluster.effects_in, [])
