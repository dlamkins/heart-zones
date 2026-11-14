import math

SNAP = 0.05
PROBE = 0.1
COLLINEAR = 1e-3


def _open(poly):
    pts = [tuple(map(float, p)) for p in poly]
    return pts[:-1] if len(pts) > 1 and pts[0] == pts[-1] else pts


def _inside(pt, poly):
    x, y = pt
    result = False
    for i in range(len(poly)):
        (x1, y1), (x2, y2) = poly[i], poly[i - 1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            result = not result
    return result


def _cross(ax, ay, bx, by):
    return ax * by - ay * bx


def _split_params(p1, p2, q1, q2):
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    ex, ey = q2[0] - q1[0], q2[1] - q1[1]
    length_sq = dx * dx + dy * dy
    ts = []
    denom = _cross(dx, dy, ex, ey)
    if abs(denom) > 1e-12:
        wx, wy = q1[0] - p1[0], q1[1] - p1[1]
        t = _cross(wx, wy, ex, ey) / denom
        u = _cross(wx, wy, dx, dy) / denom
        tol_t = SNAP / math.sqrt(length_sq)
        tol_u = SNAP / math.hypot(ex, ey)
        if -tol_t <= t <= 1 + tol_t and -tol_u <= u <= 1 + tol_u:
            ts.append(t)
    for q in (q1, q2):
        t = ((q[0] - p1[0]) * dx + (q[1] - p1[1]) * dy) / length_sq
        if 0 < t < 1 and math.dist((p1[0] + t * dx, p1[1] + t * dy), q) < SNAP:
            ts.append(t)
    return [t for t in ts if 0 < t < 1]


def _interacts(a, b):
    if any(_inside(p, b) for p in a) or any(_inside(p, a) for p in b):
        return True
    for i in range(len(a)):
        for j in range(len(b)):
            p1, p2, q1, q2 = a[i - 1], a[i], b[j - 1], b[j]
            if _split_params(p1, p2, q1, q2) or _split_params(q1, q2, p1, p2):
                return True
            if min(math.dist(p, q) for p in (p1, p2) for q in (q1, q2)) < SNAP:
                return True
    return False


def union_outlines(polygons):
    polys = [_open(p) for p in polygons]
    polys = [p for p in polys if len(p) >= 3]
    if not any(_interacts(polys[i], polys[j]) for i in range(len(polys)) for j in range(i + 1, len(polys))):
        return [list(map(list, p)) + [list(p[0])] for p in polys]

    vertices = []

    def snap(pt):
        for i, v in enumerate(vertices):
            if math.dist(v, pt) < SNAP:
                return i
        vertices.append(pt)
        return len(vertices) - 1

    pieces = []
    for pi, poly in enumerate(polys):
        for i in range(len(poly)):
            p1, p2 = poly[i - 1], poly[i]
            ts = {0.0, 1.0}
            for qi, other in enumerate(polys):
                if qi != pi:
                    for j in range(len(other)):
                        ts.update(_split_params(p1, p2, other[j - 1], other[j]))
            pts = [(p1[0] + t * (p2[0] - p1[0]), p1[1] + t * (p2[1] - p1[1])) for t in sorted(ts)]
            for a, b in zip(pts, pts[1:]):
                pieces.append((snap(a), snap(b)))

    def in_union(pt):
        return any(_inside(pt, p) for p in polys)

    edges = set()
    for a, b in pieces:
        if a == b:
            continue
        (x1, y1), (x2, y2) = vertices[a], vertices[b]
        length = math.hypot(x2 - x1, y2 - y1)
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        nx, ny = -(y2 - y1) / length * PROBE, (x2 - x1) / length * PROBE
        left, right = in_union((mx + nx, my + ny)), in_union((mx - nx, my - ny))
        if left and not right:
            edges.add((a, b))
        elif right and not left:
            edges.add((b, a))

    outgoing = {}
    for a, b in edges:
        outgoing.setdefault(a, []).append(b)

    def heading(a, b):
        return math.atan2(vertices[b][1] - vertices[a][1], vertices[b][0] - vertices[a][0])

    loops = []
    while any(outgoing.values()):
        start = min(v for v, outs in outgoing.items() if outs)
        prev, cur = start, outgoing[start].pop(0)
        loop = [start]
        while cur != start:
            loop.append(cur)
            outs = outgoing.get(cur)
            if not outs:
                raise ValueError("Polygon union produced an open boundary")
            h = heading(prev, cur)
            nxt = min(outs, key=lambda n: (heading(cur, n) - h + math.pi) % (2 * math.pi))
            outs.remove(nxt)
            prev, cur = cur, nxt
        loops.append(_simplify([vertices[i] for i in loop]))

    loops = [l for l in loops if len(l) >= 3]
    loops.sort(key=lambda l: -abs(area(l)))
    return [[[round(x, 4), round(y, 4)] for x, y in l] + [[round(l[0][0], 4), round(l[0][1], 4)]] for l in loops]


def _simplify(loop):
    changed = True
    while changed and len(loop) > 3:
        changed = False
        for i in range(len(loop)):
            a, b, c = loop[i - 1], loop[i], loop[(i + 1) % len(loop)]
            base = math.dist(a, c)
            if base and abs(_cross(b[0] - a[0], b[1] - a[1], c[0] - a[0], c[1] - a[1])) / base < COLLINEAR \
                    and (b[0] - a[0]) * (c[0] - b[0]) + (b[1] - a[1]) * (c[1] - b[1]) > 0:
                del loop[i]
                changed = True
                break
    return loop


def area(poly):
    pts = _open(poly)
    return sum(pts[i - 1][0] * pts[i][1] - pts[i][0] * pts[i - 1][1] for i in range(len(pts))) / 2
