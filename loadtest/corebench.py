"""코어 하나의 파이썬 처리 속도(게임 서버가 메시지마다 하는 일과 비슷한 것: json·deepcopy·dict·hypot). 낮을수록 빠르다."""
import json, math, time
from copy import deepcopy

player = {"id": "a" * 32, "nickname": "닉네임", "avatar": "male-1", "floor": "campus", "x": 1998.75, "y": 910.5,
          "dir": "up", "color": "#dfa34d", "moving": False, "inClassroom": False}
message = {"type": "presence.packet", "sender": "b" * 32, "payload": {"type": "move", "player": player}}
best = math.inf
for _ in range(5):
    t = time.perf_counter()
    for i in range(20000):
        json.dumps(message["payload"], ensure_ascii=False)
        deepcopy(message)
        json.loads('{"type":"input","keys":["d"]}')
        state = dict(player); state.update(x=i * 0.5, moving=True)
        math.hypot(state["x"] - 10, state["y"] - 20)
    best = min(best, time.perf_counter() - t)
print(f"{best:.4f}")
