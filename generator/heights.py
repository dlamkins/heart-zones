import glob
import json
import math
import os
import struct

MAX_SNAP = 4.0
CORNER = 0.3
SIMPLIFY = 0.25
GAP_OK = 8.0


def load(folder):
    result = {}
    for path in glob.glob(os.path.join(folder, "*.json")):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        result[int(data["taskId"])] = [tuple(map(float, p[:3])) for p in data["points"]]
    return result


def decode_trail(data):
    _, map_id = struct.unpack("<ii", data[:8])
    pts = [struct.unpack("<fff", data[o:o + 12]) for o in range(8, len(data) - 11, 12)]

    def same(a, b):
        return math.hypot(a[0] - b[0], a[2] - b[2]) < 0.05

    n = len(pts)
    if n > 2 and all(same(pts[i], pts[n - 1 - i]) for i in range(n // 2)):
        pts = pts[:(n + 1) // 2]
    pts = [p for i, p in enumerate(pts) if i == 0 or not same(p, pts[i - 1])]
    if len(pts) > 1 and same(pts[0], pts[-1]):
        pts = pts[:-1]
    return map_id, pts


def encode_trail(map_id, ring):
    loop = list(ring) + [ring[0]]
    data = bytearray(struct.pack("<ii", 0, map_id))
    for x, y, z in loop + list(reversed(loop[:-1])):
        data += struct.pack("<fff", x, y, z)
    return bytes(data)


def _project(px, pz, a, b):
    ax, az, bx, bz = a[0], a[2], b[0], b[2]
    dx, dz = bx - ax, bz - az
    length_sq = dx * dx + dz * dz
    t = 0.0 if length_sq == 0 else max(0.0, min(1.0, ((px - ax) * dx + (pz - az) * dz) / length_sq))
    return t, math.hypot(px - (ax + t * dx), pz - (az + t * dz))


def _simplify(profile):
    if len(profile) <= 2:
        return profile
    (s0, p0), (s1, p1) = profile[0], profile[-1]
    worst, index = 0.0, 0
    for i in range(1, len(profile) - 1):
        s, p = profile[i]
        expected = p0[1] + (p1[1] - p0[1]) * ((s - s0) / (s1 - s0) if s1 != s0 else 0)
        if abs(p[1] - expected) > worst:
            worst, index = abs(p[1] - expected), i
    if worst <= SIMPLIFY:
        return [profile[0], profile[-1]]
    return _simplify(profile[:index + 1])[:-1] + _simplify(profile[index:])


def apply(rings, readings):
    snapped = [[] for _ in rings]
    for x, y, z in readings:
        best = None
        for r, ring in enumerate(rings):
            for i in range(len(ring)):
                t, d = _project(x, z, ring[i], ring[(i + 1) % len(ring)])
                if best is None or d < best[0]:
                    best = (d, r, i, t)
        if best[0] <= MAX_SNAP:
            snapped[best[1]].append((best[2], best[3], y))

    result, perimeter_total, uncovered_total = [], 0.0, 0.0
    for ring, hits in zip(rings, snapped):
        n = len(ring)
        lengths = [math.hypot(ring[(i + 1) % n][0] - ring[i][0], ring[(i + 1) % n][2] - ring[i][2]) for i in range(n)]
        starts = [sum(lengths[:i]) for i in range(n)]
        perimeter = sum(lengths)
        perimeter_total += perimeter
        if not hits:
            result.append(list(ring))
            uncovered_total += perimeter
            continue

        along = sorted((starts[i] + t * lengths[i], h) for i, t, h in hits)

        def height_at(s):
            for k, (sk, hk) in enumerate(along):
                if sk >= s:
                    prev_s, prev_h = along[k - 1] if k else (along[-1][0] - perimeter, along[-1][1])
                    break
            else:
                sk, hk = along[0][0] + perimeter, along[0][1]
                prev_s, prev_h = along[-1]
            return prev_h if sk == prev_s else prev_h + (hk - prev_h) * (s - prev_s) / (sk - prev_s)

        gaps = [b[0] - a[0] for a, b in zip(along, along[1:])] + [along[0][0] + perimeter - along[-1][0]]
        uncovered_total += sum(max(0.0, g - GAP_OK) for g in gaps)

        corner_y = []
        for i in range(n):
            near = [h for e, t, h in hits if e == i and t * lengths[i] <= CORNER]
            near += [h for e, t, h in hits if e == (i - 1) % n and (1 - t) * lengths[e] <= CORNER]
            corner_y.append(sum(near) / len(near) if near else height_at(starts[i]))

        new_ring = []
        for i in range(n):
            a, b = ring[i], ring[(i + 1) % n]
            profile = [(0.0, (a[0], corner_y[i], a[2]))]
            for t, h in sorted((t, h) for e, t, h in hits if e == i):
                if CORNER < t * lengths[i] < lengths[i] - CORNER:
                    profile.append((t * lengths[i], (a[0] + t * (b[0] - a[0]), h, a[2] + t * (b[2] - a[2]))))
            profile.append((lengths[i], (b[0], corner_y[(i + 1) % n], b[2])))
            new_ring += [p for _, p in _simplify(profile)[:-1]]
        result.append(new_ring)

    coverage = 1 - uncovered_total / perimeter_total if perimeter_total else 0.0
    return result, {"readings": len(readings), "coverage": coverage}
