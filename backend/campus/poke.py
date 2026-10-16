"""Ephemeral poke effects selected from server-owned positions."""
import math
from functools import lru_cache

from .motion import World, world

COOLDOWN = .25
INPUT_LEASE = .35
SYNC_RANGE = 480
REACH = 72
SIDE_REACH = 36
DIAGONAL = 1 / math.sqrt(2)
VECTORS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0),
           "up-left": (-DIAGONAL, -DIAGONAL), "up-right": (DIAGONAL, -DIAGONAL),
           "down-left": (-DIAGONAL, DIAGONAL), "down-right": (DIAGONAL, DIAGONAL)}
STUDENT_CHAIRS = ("student-0-0-chair", "student-0-1-second-chair",
                  "student-1-0-second-chair", "student-1-1-chair")


def classroom_targets(subject):
    # These residents are drawn by CampusClassroomMap; chairs come from the same geometry.
    targets = [{"id": "classroom-instructor", "x": 385, "y": 115}]
    for chair_id in STUDENT_CHAIRS:
        chair = world(subject).objects[chair_id]["footprint"]
        targets.append({"id": "resident-" + chair_id,
                        "x": chair["x"] + chair["w"] / 2,
                        "y": chair["y"] + chair["h"] / 2, "chair": chair_id, "subject": subject})
    return targets


@lru_cache(maxsize=8)
def resident_world(subject, chair_id):
    active = world(subject)
    chair = active.objects[chair_id]["footprint"]
    # A seated resident occupies its own chair. All other furniture still blocks a poke.
    colliders = [row for row in active.data["colliders"]
                 if any(row[key] != chair[key] for key in ("x", "y", "w", "h"))]
    return World({**active.data, "colliders": colliders})


def direction_vector(active_world, direction):
    # Keyboard facing is on screen; collision and peer coordinates are on the floor.
    x, y = VECTORS[direction]
    angle, tilt = active_world.data["angle"], active_world.data["tilt"]
    dx = math.cos(angle) * x + math.sin(angle) * y / tilt
    dy = -math.sin(angle) * x + math.cos(angle) * y / tilt
    length = math.hypot(dx, dy)
    return dx / length, dy / length


def find_target(pose, targets, active_world, doors, direction=None):
    dx, dy = direction_vector(active_world, direction or pose["dir"])
    candidates = []
    for target in targets:
        x, y = target["x"] - pose["x"], target["y"] - pose["y"]
        front, side = x * dx + y * dy, abs(x * dy - y * dx)
        distance = math.hypot(x, y)
        if not 0 < front <= REACH or side > SIDE_REACH or distance > REACH:
            continue
        collision_world = resident_world(target["subject"], target["chair"]) if target.get("chair") else active_world
        if collision_world.clear(pose, target, doors):
            candidates.append((distance, target["id"]))
    return min(candidates)[1] if candidates else None
