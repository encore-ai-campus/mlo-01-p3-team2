"""Shared glass-door geometry, matching the scaled openings in dist/map-data.js."""
import math


def door(x, y, w, h, orientation, swing):
    return {"x": (x + 72) * 1.5, "y": y * 1.5, "w": w * 1.5,
            "h": h * 1.5, "orientation": orientation, "swing": swing}


DOORS = {
    "door-class4": door(475, 264, 43, 6, "horizontal", -1),
    "door-class3": door(1006, 264, 43, 6, "horizontal", -1),
    "door-class2": door(475, 366, 43, 6, "horizontal", 1),
    "door-class1": door(1006, 366, 43, 6, "horizontal", 1),
    "door-left-top": door(245, 146, 6, 38, "vertical", -1),
    "door-left-middle": door(245, 344, 6, 38, "vertical", -1),
    "door-left-bottom": door(245, 554, 6, 38, "vertical", -1),
    "door-storage": {**door(1320, 81, 33, 6, "horizontal", 1), "sliding": True, "slide": 1},
}


def footprint(geometry, opened):
    horizontal = geometry["orientation"] == "horizontal"
    length = geometry["w"] if horizontal else geometry["h"]
    thickness = geometry["h"] if horizontal else geometry["w"]
    x = geometry["x"] + (0 if horizontal else geometry["w"] / 2)
    y = geometry["y"] + (geometry["h"] / 2 if horizontal else 0)
    if geometry.get("sliding"):
        shift = (length + 6) * geometry.get("slide", 1) if opened else 0
        x += shift if horizontal else 0
        y += 0 if horizontal else shift
        return {"x": x - (0 if horizontal else thickness / 2), "y": y - (thickness / 2 if horizontal else 0),
                "w": length if horizontal else thickness, "h": thickness if horizontal else length}
    dx = (0 if horizontal else geometry["swing"] * length) if opened else (length if horizontal else 0)
    dy = (geometry["swing"] * length if horizontal else 0) if opened else (0 if horizontal else length)
    return {"x": min(x, x + dx) - (thickness / 2 if dy else 0),
            "y": min(y, y + dy) - (thickness / 2 if dx else 0),
            "w": abs(dx) + (thickness if dy else 0),
            "h": abs(dy) + (thickness if dx else 0)}


def distance(rectangle, player):
    return math.hypot(max(rectangle["x"] - player["x"], 0, player["x"] - rectangle["x"] - rectangle["w"]),
                      max(rectangle["y"] - player["y"], 0, player["y"] - rectangle["y"] - rectangle["h"]))
