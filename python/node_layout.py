"""Lay out the node graph inside a Group so an artist can read and manage it.

The main stream (the input-0 chain up from the Output) runs straight down column 0, the
B-pipe trunk. Each module (a regex of node names, see layout_hints.py) is a band of rows on
its own coloured Backdrop, the bands stacked top to bottom in the order the image flows.
Inside a band every side branch gets its own column right of the trunk and rows follow the
dependencies, so pipes only run down. Pipes between modules leave their node sideways into a
lane between two columns, run down it, and come in along a rail of Dots at the top of the
band they feed (or turn straight into the trunk node they feed).

Plain Python, no Nuke needed: build_gizmo.py runs it on the live Group (apply_nuke), and it
rewrites a saved .nk or .gizmo in place without Nuke:

    python3 python/node_layout.py groups/EzAtmosScatter_group.nk gizmos/EzAtmosScatter.gizmo

Running it again gives the same graph: Dots and Backdrops it made before are taken out first.
"""

import re

COL, ROW = 180, 60         # grid pitch in node graph units
W, H, DOT = 80, 18, 12     # default node tile and Dot sizes
RAIL = 30                  # height of one rail of Dots at the top of a band
BAND_GAP = 150             # from one band's last row to the next band's top: Backdrop label room
DOT_PREFIX = "LayoutDot"
BACKDROP_PREFIX = "Backdrop_"
# Lane slots in the gap right of a column, as x offsets of the Dot from the column's left edge.
LANES = (W + 6, W + 30, W + 54, W + 78)


class Plan(object):
    def __init__(self):
        self.pos = {}        # node name -> (x, y)
        self.dots = []       # dicts: name, input, x, y
        self.rewire = []     # (node name, input index, new input name)
        self.backdrops = []  # dicts: name, label, color, x, y, w, h, z
        self.labels = {}     # node name -> label text


def _topo(nodes, inputs):
    order, seen = [], set()

    def visit(n):
        if n in seen:
            return
        seen.add(n)
        for i in inputs[n]:
            if i is not None:
                visit(i)
        order.append(n)
    for n in nodes:
        visit(n)
    return order


def layout(nodes, modules=(), left=(), labels=None, direct=()):
    """nodes: [{'name', 'class', 'inputs': [name or None, ...]}] in creation order.
    modules: [(Backdrop label, tile_color, node name regex)] top to bottom; first match wins.
    left: name regexes of side chains to put left of the trunk instead of right.
    labels: {node name: label text} to show on nodes (keep it free of [ ] and quotes).
    direct: names of nodes whose inputs never go through Dots (tool code rewires them)."""
    plan = Plan()
    plan.labels = dict(labels or {})
    cls = dict((n["name"], n["class"]) for n in nodes)
    inputs = dict((n["name"], [i if i in cls else None for i in n["inputs"]]) for n in nodes)
    # Up from the Output first, then whatever does not feed it, by name: the same order
    # whether the nodes came from Nuke or from a saved file.
    outs = [n["name"] for n in nodes if n["class"] == "Output"]
    order = _topo(outs + sorted(cls), inputs)
    rank = dict((n, k) for k, n in enumerate(order))
    consumers = dict((n, []) for n in order)
    for n in order:
        for i, src in enumerate(inputs[n]):
            if src is not None:
                consumers[src].append((n, i))

    # The trunk: up the input-0 chain from the Output.
    trunk, n = [], outs[0] if outs else order[-1]
    while n is not None:
        trunk.insert(0, n)
        n = inputs[n][0] if inputs[n] else None
    on_trunk = set(trunk)

    rules = list(modules) + [("Other", 0x444444ff, r".*")]
    band = dict((n, next(k for k, r in enumerate(rules) if re.match(r[2] + "$", n))) for n in order)

    # Rows inside each band: longest path from the band's own nodes; inputs from other bands
    # come in at the top. Sources without inputs sit just above their first user.
    row = {}
    for n in order:
        ins = [row[i] + 1 for i in inputs[n] if i is not None and band[i] == band[n]]
        row[n] = max(ins) if ins else 0
    for n in order:
        users = [row[c] for c, _ in consumers[n] if band[c] == band[n]]
        if cls[n] != "Input" and not [i for i in inputs[n] if i is not None] and users:
            row[n] = max(0, min(users) - 1)

    # Chains: a node continues the column of its input 0 (same band) when it is that node's
    # first user; anything else starts a new chain.
    chain_of, chains = {}, []
    for n in order:
        if n in on_trunk:
            continue
        src = inputs[n][0] if inputs[n] else None
        if (src is not None and src not in on_trunk and band[src] == band[n] and chain_of[src][-1] == src and
                min(rank[c] for c, i in consumers[src] if i == 0 and c not in on_trunk and band[c] == band[n]) == rank[n]):
            chain_of[n] = chain_of[src]
            chain_of[n].append(n)
        else:
            chain_of[n] = [n]
            chains.append(chain_of[n])

    # Columns: each chain takes the nearest free column on its side of the trunk, at or beyond
    # the column of the chain it branches from, with a free row above and below it.
    col = dict((n, 0) for n in trunk)
    used = {}
    for chain in chains:
        b, top, bottom = band[chain[0]], row[chain[0]], row[chain[-1]]
        side = -1 if any(re.match(r + "$", chain[0]) for r in left) else 1
        src = inputs[chain[0]][0] if inputs[chain[0]] else None
        start = side * col[src] if src is not None and band[src] == b and src in col else 1
        c = side * max(1, start)
        while any(a <= bottom + 1 and top - 1 <= z for a, z in used.get((b, c), [])):
            c += side
        used.setdefault((b, c), []).append((top, bottom))
        for n in chain:
            col[n] = c

    # Bands top to bottom, each with a rail per outside source feeding its side nodes.
    rails, y = {}, 0
    band_y = {}
    for b in range(len(rules)):
        members = [n for n in order if band[n] == b]
        if not members:
            continue
        feeds = []
        for n in members:
            if n in on_trunk:
                continue
            for src in inputs[n]:
                if src is not None and band[src] != b and src not in feeds:
                    feeds.append(src)
        feeds.sort(key=lambda s: (plan.pos[s][0], plan.pos[s][1]) if s in plan.pos else (0, 0))
        for k, src in enumerate(feeds):
            rails[(b, src)] = y + k * RAIL + (RAIL - DOT) // 2
        band_y[b] = y + len(feeds) * RAIL + (RAIL if feeds else 0)
        for n in members:
            plan.pos[n] = (col[n] * COL, band_y[b] + row[n] * ROW)
        y = band_y[b] + max(row[n] for n in members) * ROW + H + BAND_GAP

    cell = set((band[n], col[n], row[n]) for n in order)
    _route(plan, order, inputs, consumers, band, col, row, cell, rails, on_trunk, set(direct))
    _unblock_steps(plan, order, inputs, col)
    _nudge(plan, order, inputs)
    _backdrops(plan, order, rules, band, rails)
    return plan


def _route(plan, order, inputs, consumers, band, col, row, cell, rails, on_trunk, direct):
    lanes = {}  # x -> [(y0, y1)] already running down that lane
    drops = []  # (x, y) of the Dots rails drop into nodes from, which lanes keep clear of

    def drop_x(x, y):
        """x for a rail's drop Dot, moved off any lane already running past it."""
        for shift in (0, 6, -6, 12, -12, 18, -18, 24, -24):
            if not any(abs(lx - (x + shift)) < DOT + 4 and a - DOT < y < z + DOT
                       for lx, spans in lanes.items() for a, z in spans):
                drops.append((x + shift, y))
                return x + shift
        drops.append((x, y))
        return x
    rank_of = dict((n, k) for k, n in enumerate(order))
    routed = {}  # (source, node) -> what the node's input now points at

    def free(b, c, r):
        return (b, c, r) not in cell

    def clear_col(b, c, r0, r1):  # rows strictly between r0 and r1
        return all(free(b, c, r) for r in range(r0 + 1, r1))

    def clear_row(b, r, c0, c1):  # columns strictly between c0 and c1
        return all(free(b, c, r) for c in range(min(c0, c1) + 1, max(c0, c1)))

    def lane(c, y0, y1, step=1):
        """x of a free lane from y0 to y1 in the gap right of column c, or the next gap over."""
        for g in range(c, c + step * 8, step):
            for off in LANES:
                x = g * COL + off
                if all(y1 < a - DOT - 4 or z + DOT + 4 < y0 for a, z in lanes.get(x, [])) and \
                        not any(abs(px - x) < DOT + 4 and y0 - DOT < py < y1 + DOT for px, py in drops):
                    lanes.setdefault(x, []).append((y0, y1))
                    return x
        return c * COL + LANES[-1]

    def dot(src, x, y):
        name = "%s%d" % (DOT_PREFIX, len(plan.dots) + 1)
        plan.dots.append({"name": name, "input": src, "x": int(x), "y": int(y)})
        return name

    def centre_y(n):
        return plan.pos[n][1] + (H - DOT) // 2

    def mid_x(c):
        return c * COL + (W - DOT) // 2

    def connect(n, i, src, via):
        routed[(src, n)] = via
        if via != src:
            plan.rewire.append((n, i, via))

    # Pipes inside a band that are a straight drop, a short step, or one bend.
    far = dict((n, []) for n in order)  # source -> [(node, input)] still to route
    corners = {}  # (source, along, side) -> one-bend pipes, see below
    for n in order:
        for i, src in enumerate(inputs[n]):
            if src is None:
                continue
            b, cs, rs, cd, rd = band[n], col[src], row[src], col[n], row[n]
            if n in direct:
                connect(n, i, src, src)
            elif (src, n) in routed:
                if routed[(src, n)] != src:
                    plan.rewire.append((n, i, routed[(src, n)]))
            elif band[src] != b:
                if n in on_trunk and i == 0 and src in on_trunk:
                    connect(n, i, src, src)
                else:
                    far[src].append((n, i))
            elif cs == cd and clear_col(b, cs, rs, rd) or rd - rs == 1 and abs(cs - cd) <= 1 or \
                    rd == rs and clear_row(b, rs, cs, cd):
                connect(n, i, src, src)
            elif free(b, cd, rs) and clear_row(b, rs, cs, cd) and clear_col(b, cd, rs, rd):
                corners.setdefault((src, "row", cd > cs), []).append((abs(cd - cs), mid_x(cd), centre_y(src), n, i))
            elif free(b, cs, rd) and clear_col(b, cs, rs, rd + 1) and clear_row(b, rd, cs, cd):
                corners.setdefault((src, "col", 0), []).append((rd - rs, mid_x(cs), centre_y(n), n, i))
            else:
                far[src].append((n, i))
    def side_of(src, n):
        return 1 if col[src] >= col[n] else -1

    def into_side(src, n):  # comes in from the side rather than along a rail
        return band[n] == band[src] or n in on_trunk

    # A bend into the side of a node that other pipes also come into from that side becomes a
    # lane pipe too, so they can all be given their own height.
    side_ins = set((n, side_of(src, n)) for src in order for n, i in far[src] if into_side(src, n))
    for key in list(corners):
        if key[1] == "col":
            src = key[0]
            for item in list(corners[key]):
                if (item[3], side_of(src, item[3])) in side_ins:
                    corners[key].remove(item)
                    far[src].append((item[3], item[4]))

    # One bend each: the Dots one source turns at along the same line follow on from each other,
    # nearest first, so the pipes run end to end instead of on top of each other.
    for (src, _, _), line in sorted(corners.items(), key=lambda c: rank_of[c[0][0]]):
        last, at = src, {}
        for _, x, y, n, i in sorted(line):
            if (x, y) not in at:
                last = at[(x, y)] = dot(last, x, y)
            if (src, n) in routed:
                plan.rewire.append((n, i, routed[(src, n)]))
            else:
                connect(n, i, src, at[(x, y)])

    # The rest leave their source sideways into a lane, one lane per source, and run down it.
    # Into another band's side node: along that band's rail to a Dot above it, each rail at its
    # own spot so no pipe runs through another rail's Dot. Into anything else: from the lane
    # beside it, several pipes into one node coming in at different heights (the nearest lane
    # highest, and clear of the node's own pipes out on that side), so none crosses a Dot.
    def kind(src, n):
        """How a lane pipe gets into n: 'rail' (down from its band's rail), 'beside' (from the
        rail down a lane beside n, its column being taken), 'in' (level from the source's lane)
        or 'over' (n's row is blocked that far: across the gap above, down a lane beside n)."""
        b, cd, rd = band[n], col[n], row[n]
        if not into_side(src, n):
            return "rail" if clear_col(b, cd, -1, rd) else "beside"
        g = col[src]
        between = range(cd + 1, g + 1) if g >= cd else range(g + 1, cd)
        return "in" if all(free(b, c, rd) for c in between) else "over"

    # Everything coming into one side of a node gets its own height there, the nearest lane
    # highest, and clear of the node's own pipe out on that side.
    entries = {}  # (node, side) -> sorted [(distance, source)]
    for src in order:
        for n, i in far[src]:
            how = kind(src, n)
            if how != "rail":
                key = (abs(col[src] - col[n]) if how == "in" else 0, rank_of[src])
                if key not in entries.setdefault((n, side_of(src, n)), []):
                    entries[(n, side_of(src, n))].append(key)
    for k in entries:
        entries[k].sort()

    def busy_side(n, side):  # does a pipe leave n level on this side?
        return side == 1 and bool(far[n]) or bool(corners.get((n, "row", side == 1)))

    def entry_y(src, n):
        side = side_of(src, n)
        ins = entries[(n, side)]
        how = kind(src, n)
        if how != "in":
            return centre_y(n)  # down a lane right beside n: in level
        k = ins.index((abs(col[src] - col[n]), rank_of[src]))
        # Above whatever comes in level beside it, or leaves level on that side.
        level = busy_side(n, side) or any(key[0] == 0 for key in ins)
        up = len(ins) - 1 - k + (1 if level else 0)
        return centre_y(n) - up * RAIL

    def rail_dx(n, y):
        ys = sorted(set(rails[(band[n], s)] for s in inputs[n] if s is not None and (band[n], s) in rails))
        k = ys.index(y)
        # Centre out: the top rail straight above, the next ones either side of it.
        return int(((k + 1) // 2) * (1 if k % 2 else -1) * 18)

    tracks = {}  # (band, row) -> [(x0, x1, y)] pipes running across the gap above that row

    def track(n, xa, xb, up=0):
        """y of a free track from xa to xb across the gap above n's row (two tracks there), or
        when those are taken, above one of the up rows over it."""
        lo, hi = min(xa, xb) - DOT, max(xa, xb) + DOT
        for k in range(up + 1):
            taken = tracks.setdefault((band[n], row[n] - k), [])
            top = plan.pos[n][1] - k * ROW
            for y in (top - 6 - DOT, top - 20 - DOT):
                if not any(ty == y and a < hi and lo < z for a, z, ty in taken):
                    taken.append((lo, hi, y))
                    return y
        return None

    def near_x(n, x):  # a Dot in the gap beside n, on x's side
        right = x > plan.pos[n][0]
        return plan.pos[n][0] + (W + (COL - W) // 2 if right else -(COL - W) // 2) - DOT // 2

    for src in order:
        if not far[src]:
            continue
        bottom = max(rails[(band[n], src)] if not into_side(src, n) else centre_y(n) for n, _ in far[src])
        x = lane(col[src], centre_y(src), bottom)
        legs = []  # (y on the lane, x it heads to, how, node, input, y it comes in at)
        for n, i in far[src]:
            b, cd, rd = band[n], col[n], row[n]
            how = kind(src, n)
            if how == "rail":
                y = rails[(b, src)]
                legs.append((y, drop_x(mid_x(cd) + rail_dx(n, y), y), how, n, i, None))
                continue
            up = row[n] - row[src] - 1 if band[src] == b else row[n]
            if how == "in":
                y = max(entry_y(src, n), centre_y(src) + RAIL)
                if y < centre_y(n):
                    y = track(n, x, near_x(n, x))
                if y is not None:
                    legs.append((max(y, centre_y(src) + RAIL), x, how, n, i, None))
                    continue
                how = "over"
            # Down a lane beside n: from the rail, or along a track in the gap above n's row.
            if how == "beside":
                y = rails[(b, src)]
            else:
                y = track(n, x, mid_x(cd), up)
                if y is None:
                    y = plan.pos[n][1] - 6 - DOT
            side = side_of(src, n)
            lx = lane(cd if side > 0 else cd - 1, y, centre_y(n), side)
            legs.append((y, lx, how, n, i, entry_y(src, n) if how == "beside" else centre_y(n)))
        prev = dot(src, x, centre_y(src))
        for y in sorted(set(l[0] for l in legs)):
            stop = prev = dot(prev, x, y)
            last = {-1: stop, 1: stop}
            for _, tx, how, n, i, ey in sorted((l for l in legs if l[0] == y), key=lambda l: abs(l[1] - x)):
                if (src, n) in routed:
                    plan.rewire.append((n, i, routed[(src, n)]))
                    continue
                if how == "in":
                    # From above its level and further than the next gap over: on to a Dot in
                    # that gap first, so the slope stays short and clear of its own pipe out.
                    near = near_x(n, x)
                    if y < centre_y(n) and abs(x - near) > (COL - W) // 2:
                        connect(n, i, src, dot(stop, near, y))
                    else:
                        connect(n, i, src, stop)
                    continue
                side = 1 if tx >= x else -1
                last[side] = dot(last[side], tx, y)
                if how == "rail" or ey - y < 2 * DOT:
                    connect(n, i, src, last[side])
                else:
                    connect(n, i, src, dot(last[side], tx, ey))


def _near_pipe(box, a, b, clear=3):
    """Is box (x, y, w, h) on the straight pipe between points a and b?"""
    (x0, y0), (x1, y1) = a, b
    x, y, w, h = box
    cx, cy = x + w / 2.0, y + h / 2.0
    length2 = max((x1 - x0) ** 2 + (y1 - y0) ** 2, 1e-9)
    t = max(0.0, min(1.0, ((cx - x0) * (x1 - x0) + (cy - y0) * (y1 - y0)) / length2))
    return abs(x0 + t * (x1 - x0) - cx) < w / 2.0 + clear and abs(y0 + t * (y1 - y0) - cy) < h / 2.0 + clear


def _unblock_steps(plan, order, inputs, col):
    """A short diagonal step from one column to the next that runs over a Dot gets a bend
    instead: across at the source's height then down, or down then across."""
    final = dict((n, list(inputs[n])) for n in order)
    for n, i, src in plan.rewire:
        final[n][i] = src
    boxes = [(n, (x, y, W, H)) for n, (x, y) in plan.pos.items()]
    boxes += [(d["name"], (d["x"], d["y"], DOT, DOT)) for d in plan.dots]

    def centre(box):
        return box[0] + box[2] / 2.0, box[1] + box[3] / 2.0

    def clear(a, b, skip):
        return not any(_near_pipe(box, a, b) for m, box in boxes if m not in skip)
    for n in order:
        for i, src in enumerate(final[n]):
            if src not in plan.pos or col[src] == col[n]:
                continue
            a, b = centre(plan.pos[src] + (W, H)), centre(plan.pos[n] + (W, H))
            if clear(a, b, (src, n)):
                continue
            for corner in ((b[0], a[1]), (a[0], b[1])):
                d = {"name": "%s%d" % (DOT_PREFIX, len(plan.dots) + 1), "input": src,
                     "x": int(corner[0] - DOT / 2.0), "y": int(corner[1] - DOT / 2.0)}
                dbox = (d["x"], d["y"], DOT, DOT)
                if clear(a, corner, (src, n, d["name"])) and clear(corner, b, (src, n, d["name"])) and \
                        not any(_near_pipe(dbox, centre(box), centre(box), 6) for m, box in boxes if m not in (src, n)):
                    plan.dots.append(d)
                    plan.rewire.append((n, i, d["name"]))
                    boxes.append((d["name"], dbox))
                    break


def _nudge(plan, order, inputs):
    """Last pass: a Dot still sitting on someone else's pipe slides a little along its own
    pipes (up or down its lane, or along its track) to where it is clear."""
    final = dict((n, list(inputs[n])) for n in order)
    for n, i, src in plan.rewire:
        final[n][i] = src
    by_name = dict((d["name"], d) for d in plan.dots)

    def box(m):
        if m in by_name:
            return by_name[m]["x"], by_name[m]["y"], DOT, DOT
        return plan.pos[m] + (W, H)

    def centre(m):
        x, y, w, h = box(m)
        return x + w / 2.0, y + h / 2.0
    links = [(s, n) for n in order for s in final[n] if s is not None]
    links += [(d["input"], d["name"]) for d in plan.dots]
    names = list(plan.pos) + list(by_name)

    def problems(m):  # pipes m sits on, and boxes m's own pipes run through
        bad = sum(1 for a, b in links if m not in (a, b) and _near_pipe(box(m), centre(a), centre(b)))
        for a, b in links:
            if m in (a, b):
                bad += sum(1 for o in names if o not in (a, b) and _near_pipe(box(o), centre(a), centre(b)))
        return bad

    def downhill(m):  # no pipe of m may run up
        cy = centre(m)[1]
        return all(centre(a)[1] <= cy + 1 for a, b in links if b == m) and \
            all(cy <= centre(b)[1] + 1 for a, b in links if a == m)
    for d in plan.dots:
        m = d["name"]
        start = problems(m)
        if not start:
            continue
        x0, y0 = d["x"], d["y"]
        best = (start, x0, y0)
        for dx, dy in ((0, 7), (0, -7), (0, 12), (0, -12), (7, 0), (-7, 0), (12, 0), (-12, 0)):
            d["x"], d["y"] = x0 + dx, y0 + dy
            if downhill(m):
                p = problems(m)
                if p < best[0]:
                    best = (p, d["x"], d["y"])
        d["x"], d["y"] = best[1], best[2]


def _backdrops(plan, order, rules, band, rails):
    boxes = []
    for b, rule in enumerate(rules):
        ns = [n for n in order if band[n] == b]
        if not ns:
            continue
        xs = [plan.pos[n][0] for n in ns]
        ys = [plan.pos[n][1] for n in ns] + [y for (bb, _), y in rails.items() if bb == b]
        x, y = min(xs) - 40, min(ys) - 60
        boxes.append({"name": BACKDROP_PREFIX + re.sub(r"\W+", "_", rule[0]).strip("_"),
                      "label": rule[0], "color": rule[1], "x": x, "y": y,
                      "w": max(xs) + W + 40 - x, "h": max(ys) + H + 40 - y})
    for k, b in enumerate(sorted(boxes, key=lambda b: -b["w"] * b["h"])):
        b["z"] = k
    plan.backdrops = boxes


def check(plan, classes, inputs, gap=6):
    """Problems with a plan: nodes or Dots that touch, and pipes that run up."""
    boxes = [(n, x, y, DOT if classes.get(n) == "Dot" else W, DOT if classes.get(n) == "Dot" else H)
             for n, (x, y) in plan.pos.items()]
    boxes += [(d["name"], d["x"], d["y"], DOT, DOT) for d in plan.dots]
    problems = []
    for k, (a, ax, ay, aw, ah) in enumerate(boxes):
        for b, bx, by, bw, bh in boxes[k + 1:]:
            if ax < bx + bw + gap and bx < ax + aw + gap and ay < by + bh + gap and by < ay + ah + gap:
                problems.append("touching: %s, %s" % (a, b))
    where = dict((b[0], (b[2], b[4])) for b in boxes)
    links = [(s, n) for n, ins in inputs.items() for s in ins if s is not None]
    links += [(d["input"], d["name"]) for d in plan.dots]
    for s, n in links:
        if s in where and n in where and where[s][0] + where[s][1] / 2.0 > where[n][0] + where[n][1] / 2.0 + 1:
            problems.append("runs up: %s -> %s" % (s, n))
    # A Dot sitting on a pipe it is not part of, or a pipe running through a node, reads as a
    # connection that is not there.
    box = dict((b[0], b[1:]) for b in boxes)

    def centre(n):
        x, y, w, h = box[n]
        return x + w / 2.0, y + h / 2.0
    for s, n in set(links):
        if s not in box or n not in box:
            continue
        (x0, y0), (x1, y1) = centre(s), centre(n)
        length2 = max((x1 - x0) ** 2 + (y1 - y0) ** 2, 1e-9)
        for m, (x, y, w, h) in box.items():
            if m in (s, n):
                continue
            # Nearest point of the pipe to the box centre, then how far inside the box it is.
            cx, cy = x + w / 2.0, y + h / 2.0
            t = max(0.0, min(1.0, ((cx - x0) * (x1 - x0) + (cy - y0) * (y1 - y0)) / length2))
            px, py = x0 + t * (x1 - x0), y0 + t * (y1 - y0)
            if abs(px - cx) < w / 2.0 + 3 and abs(py - cy) < h / 2.0 + 3:
                problems.append("on a pipe: %s on %s -> %s" % (m, s, n))
    for k, a in enumerate(plan.backdrops):
        for b in plan.backdrops[k + 1:]:
            if a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"] and \
                    a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"]:
                problems.append("backdrops overlap: %s, %s" % (a["label"], b["label"]))
    return problems


def _final_inputs(nodes, plan):
    inputs = dict((n["name"], list(n["inputs"])) for n in nodes)
    for n, i, src in plan.rewire:
        inputs[n][i] = src
    return inputs


# --- Nuke --------------------------------------------------------------------------------

def apply_nuke(group, **hints):
    """Lay out the nodes inside a live Group. Returns the list of layout problems."""
    import nuke
    with group:
        for n in nuke.allNodes():
            if n.Class() == "Dot" and n.name().startswith(DOT_PREFIX):
                for user in n.dependent(nuke.INPUTS | nuke.HIDDEN_INPUTS, forceEvaluate=False):
                    for i in range(user.inputs()):
                        if user.input(i) is n:
                            user.setInput(i, n.input(0))
                nuke.delete(n)
            elif n.Class() == "BackdropNode" and n.name().startswith(BACKDROP_PREFIX):
                nuke.delete(n)
        nodes = [{"name": n.name(), "class": n.Class(),
                  "inputs": [n.input(i).name() if n.input(i) is not None else None for i in range(n.inputs())]}
                 for n in nuke.allNodes() if n.Class() not in ("BackdropNode", "StickyNote")]
        plan = layout(nodes, **hints)
        for name, (x, y) in plan.pos.items():
            nuke.toNode(name).setXYpos(int(x), int(y))
        for name, text in plan.labels.items():
            if nuke.toNode(name) is not None:
                nuke.toNode(name)["label"].setValue(text)
        for d in plan.dots:
            nuke.nodes.Dot(name=d["name"], xpos=d["x"], ypos=d["y"])
        for d in plan.dots:
            nuke.toNode(d["name"]).setInput(0, nuke.toNode(d["input"]))
        for name, i, src in plan.rewire:
            nuke.toNode(name).setInput(i, nuke.toNode(src))
        for b in plan.backdrops:
            nuke.nodes.BackdropNode(name=b["name"], label=b["label"], tile_color=b["color"], note_font_size=32,
                                    xpos=b["x"], ypos=b["y"], bdwidth=b["w"], bdheight=b["h"], z_order=b["z"])
        return check(plan, dict((n["name"], n["class"]) for n in nodes), _final_inputs(nodes, plan))


# --- .nk text ----------------------------------------------------------------------------

def _parse_nk(text):
    """The Group/Gizmo body of a saved .nk: (head lines, nodes, tail lines). Each node keeps
    its own lines; wiring comes from replaying the push/set stack."""
    lines = text.split("\n")
    start = next(k for k, l in enumerate(lines) if re.match(r"^(Group|Gizmo) \{", l))
    k = next(k for k in range(start, len(lines)) if lines[k] == "}") + 1
    end = next(j for j in range(k, len(lines)) if lines[j] == "end_group")
    stack, var, nodes, extra = [], {}, [], []
    while k < end:
        line = lines[k]
        m = re.match(r"^ (\w+) \{$", line)
        if m:
            s = k
            while lines[k] != " }":
                k += 1
            body = lines[s:k + 1]
            count = 1
            name = None
            for b in body:
                c = re.match(r"^  inputs (\d+)(?:\+(\d+))?", b)
                if c:
                    count = int(c.group(1)) + int(c.group(2) or 0)
                c = re.match(r"^  name (\S+)", b)
                if c:
                    name = c.group(1)
            ins = [stack.pop() if stack else None for _ in range(count)]
            nodes.append({"name": name, "class": m.group(1), "inputs": ins, "body": body})
            stack.append(name)
        elif line.startswith("push "):
            v = line.split()[1]
            stack.append(None if v == "0" else var[v[1:]])
        elif line.startswith("set "):
            var[line.split()[1]] = stack[-1]
        elif line.startswith("add_layer "):
            extra.append(line)
        elif line.strip():
            raise ValueError("unexpected line in group: %r" % line)
        k += 1
    head = lines[:next(k for k in range(start, len(lines)) if lines[k] == "}") + 1]
    return head + extra, nodes, lines[end:]


def _set_knob(body, knob, value):
    body = [b for b in body if not re.match(r"^  %s " % knob, b)]
    return body[:-1] + ["  %s %s" % (knob, value), body[-1]]


def apply_nk(path, **hints):
    """Lay out the Group/Gizmo saved in path, in place. Returns the list of layout problems."""
    with open(path) as f:
        text = f.read()
    head, nodes, tail = _parse_nk(text)
    nodes = [n for n in nodes if not (n["class"] == "BackdropNode" and n["name"].startswith(BACKDROP_PREFIX))]
    # Take out Dots from an earlier layout, joining their pipes back up.
    old = dict((n["name"], n["inputs"][0]) for n in nodes if n["class"] == "Dot" and n["name"].startswith(DOT_PREFIX))

    def real(name):
        while name in old:
            name = old[name]
        return name
    nodes = [dict(n, inputs=[real(i) for i in n["inputs"]]) for n in nodes if n["name"] not in old]
    plan = layout(nodes, **hints)
    inputs = _final_inputs(nodes, plan)
    bodies = {}
    for n in nodes:
        body = n["body"]
        x, y = plan.pos[n["name"]]
        body = _set_knob(_set_knob(body, "xpos", int(x)), "ypos", int(y))
        if n["name"] in plan.labels:
            body = _set_knob(body, "label", '"%s"' % plan.labels[n["name"]])
        bodies[n["name"]] = body
    for d in plan.dots:
        inputs[d["name"]] = [d["input"]]
        bodies[d["name"]] = [" Dot {", "  name " + d["name"], "  xpos %d" % d["x"], "  ypos %d" % d["y"], " }"]
    out = []
    for b in plan.backdrops:
        out += [" BackdropNode {", "  inputs 0", "  name " + b["name"], "  tile_color 0x%08x" % b["color"],
                '  label "%s"' % b["label"], "  note_font_size 32", "  xpos %d" % b["x"], "  ypos %d" % b["y"],
                "  bdwidth %d" % b["w"], "  bdheight %d" % b["h"], "  z_order %d" % b["z"], " }"]
    # Write every node after its inputs, each followed by a stack variable its users push.
    var, done = {}, set()

    def emit(name):
        if name in done:
            return
        done.add(name)
        for i in inputs[name]:
            if i is not None:
                emit(i)
        for i in reversed(inputs[name]):
            out.append("push $" + var[i] if i is not None else "push 0")
        out.extend(bodies[name])
        var[name] = "N%08x" % (0x1a700000 + len(var))
        out.append("set %s [stack 0]" % var[name])
    for n in nodes:
        emit(n["name"])
    with open(path, "w") as f:
        f.write("\n".join(head + out + tail))
    return check(plan, dict((n["name"], n["class"]) for n in nodes), inputs)


if __name__ == "__main__":
    import sys
    import layout_hints
    status = 0
    for path in sys.argv[1:]:
        problems = apply_nk(path, **layout_hints.HINTS)
        for p in problems:
            print("%s: %s" % (path, p))
        print("%s: laid out, %d problems" % (path, len(problems)))
        status = status or bool(problems)
    sys.exit(status)
