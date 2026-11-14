import glob
import html
import json
import os
import re
import struct
import time
import urllib.request

import heights as ground
from polygons import union_outlines

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OVERRIDES_DIR = os.path.join(HERE, "overrides")

API_FLOOR_LIST = "https://api.guildwars2.com/v2/continents/{continent}/floors"
API_MAP_FLOOR = "https://api.guildwars2.com/v1/map_floor.json?continent_id={continent}&floor={floor}"

warnings = []


def warn(message):
    warnings.append(message)
    print(f"::warning::{message}")


def fetch_json(url, attempts=5):
    for attempt in range(1, attempts + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "heart-zones-generator"})
            with urllib.request.urlopen(req, timeout=60) as response:
                return json.load(response)
        except Exception as ex:
            if attempt == attempts:
                raise RuntimeError(f"Failed to fetch {url}: {ex}") from ex
            time.sleep(2 ** attempt)


def f32(value):
    return struct.unpack("<f", struct.pack("<f", value))[0]


METRIC = f32(f32(1 / 254) * 10000)


def encode_trail(map_id, game_map, bounds):
    map_rect, cont_rect = game_map["map_rect"], game_map["continent_rect"]
    map_width = f32(map_rect[1][0] - map_rect[0][0])
    cont_width = f32(cont_rect[1][0] - cont_rect[0][0])
    map_height = f32(map_rect[0][1] - map_rect[1][1])
    cont_height = f32(cont_rect[1][1] - cont_rect[0][1])

    def raw_x(x):
        return f32(f32(f32(f32(f32(f32(x) - cont_rect[0][0]) / cont_width) * map_width) + map_rect[0][0]) / METRIC)

    def raw_z(y):
        return f32(f32(f32(f32(f32(f32(y) - cont_rect[0][1]) / cont_height) * map_height) + map_rect[1][1]) / METRIC)

    data = bytearray(struct.pack("<ii", 0, map_id))
    for x, y in list(bounds) + list(reversed(bounds[:-1])):
        data += struct.pack("<fff", raw_x(x), 0.0, raw_z(y))
    return bytes(data)


def collect(continents):
    tasks = {}
    for continent in continents:
        floors = sorted(fetch_json(API_FLOOR_LIST.format(continent=continent)))
        for floor in floors:
            data = fetch_json(API_MAP_FLOOR.format(continent=continent, floor=floor))
            for region in (data.get("regions") or {}).values():
                for map_key, game_map in sorted((region.get("maps") or {}).items(), key=lambda kv: int(kv[0])):
                    map_id = int(map_key)
                    for task in game_map.get("tasks") or []:
                        task_id = task["task_id"]
                        entry = tasks.setdefault(task_id, {
                            "map_id": map_id,
                            "map_name": game_map["name"],
                            "objective": task["objective"].strip(),
                            "game_map": game_map,
                            "polygons": [],
                        })
                        if entry["map_id"] != map_id:
                            continue
                        bounds = task.get("bounds") or []
                        polygon = {"bounds": bounds, "trail": encode_trail(map_id, game_map, bounds)}
                        if all(p["trail"] != polygon["trail"] for p in entry["polygons"]):
                            entry["polygons"].append(polygon)
    return tasks


def xml_comment(text):
    return text.replace("--", "- -")


def trail_sort_key(name):
    match = re.match(r"(\d+)(?:_(\d+))?\.trl$", os.path.basename(name))
    return int(match.group(1)), int(match.group(2) or 0)


def override_trails(task_id):
    paths = glob.glob(os.path.join(OVERRIDES_DIR, f"{task_id}.trl")) + \
        glob.glob(os.path.join(OVERRIDES_DIR, f"{task_id}_*.trl"))
    return [(os.path.basename(p), open(p, "rb").read()) for p in sorted(paths, key=trail_sort_key)]


def apply_heights(label, files, readings, report):
    decoded = [ground.decode_trail(data) for _, data in files]
    rings, stats = ground.apply([ring for _, ring in decoded], readings)
    report["grounded"].append(f"{label}: {stats['readings']} readings, {stats['coverage']:.0%} covered")
    if stats["coverage"] < 0.9:
        warn(f"Heart {label}: recorded heights only cover {stats['coverage']:.0%} of the outline.")
    return [(name, ground.encode_trail(map_id, ring)) for (name, _), (map_id, _), ring in zip(files, decoded, rings)]


def build(tasks, config, heights):
    category = config["category"]
    excluded = {int(k): v for k, v in config["excludeTasks"].items()}
    map_attrs = {int(k): v for k, v in config["mapAttributes"].items()}
    task_attrs = {int(k): v for k, v in config["taskAttributes"].items()}

    maps, trails = {}, {}
    report = {"excluded": [], "overridden": [], "unusable": [], "multi": [], "grounded": []}

    for task_id in sorted(tasks):
        task = tasks[task_id]
        label = f"{task_id} ({task['map_name']}: {task['objective']})"

        if task_id in excluded:
            report["excluded"].append(f"{label}: {excluded[task_id]}")
            continue

        files = override_trails(task_id)
        if files:
            report["overridden"].append(label)
        else:
            usable = [p for p in task["polygons"] if len(p["bounds"]) > 3]
            if not usable:
                warn(f"Heart {label} has no usable bounds in the API and no override; it was left out.")
                report["unusable"].append(label)
                continue
            outlines = [p["trail"] for p in usable]
            if len(usable) > 1:
                merged = union_outlines([p["bounds"] for p in usable])
                outlines = [encode_trail(task["map_id"], task["game_map"], loop) for loop in merged]
                report["multi"].append(f"{label}: {len(usable)} pieces -> {len(outlines)} outline(s)")
            files = [(f"{task_id}.trl" if i == 0 else f"{task_id}_{i}.trl", t) for i, t in enumerate(outlines)]

        if heights.get(task_id):
            files = apply_heights(label, files, heights[task_id], report)

        attrs = {**map_attrs.get(task["map_id"], {}), **task_attrs.get(task_id, {})}
        extra = "".join(f' {k}="{html.escape(str(v), quote=True)}"' for k, v in attrs.items())
        lines = maps.setdefault(task["map_id"], (task["map_name"], []))[1]
        for name, data in files:
            trails[name] = data
            lines.append(f'<trail type="{category}" mapId="{task["map_id"]}" trailData="trails\\{name}"{extra} />'
                         f'<!-- {xml_comment(task["objective"])} -->')

    return maps, trails, report


def write_output(maps, trails):
    trails_dir = os.path.join(ROOT, "trails")
    for path in glob.glob(os.path.join(ROOT, "map*.xml")) + glob.glob(os.path.join(trails_dir, "*.trl")):
        os.remove(path)
    os.makedirs(trails_dir, exist_ok=True)

    for name, data in trails.items():
        with open(os.path.join(trails_dir, name), "wb") as f:
            f.write(data)
    for map_id, (map_name, lines) in maps.items():
        with open(os.path.join(ROOT, f"map{map_id}.xml"), "w", encoding="utf-8", newline="\n") as f:
            f.write(f"<OverlayData><POIs><!-- {xml_comment(map_name)} -->\n")
            f.write("\n".join(lines) + "\n")
            f.write("</POIs></OverlayData>\n")


def write_summary(tasks, maps, trails, report):
    out = ["## Heart zone generation", "",
           f"- {len(tasks)} hearts in the API, {len(trails)} trails written across {len(maps)} maps."]
    sections = [("Excluded", "excluded"), ("Overridden", "overridden"),
                ("Left out (no usable bounds)", "unusable"), ("Merged from multiple polygons", "multi"),
                ("Recorded heights", "grounded")]
    for title, key in sections:
        if report[key]:
            out += ["", f"<details><summary>{title} ({len(report[key])})</summary>", ""]
            out += [f"- {item}" for item in report[key]]
            out += ["", "</details>"]
    if warnings:
        out += ["", "### Warnings", ""] + [f"- {w}" for w in warnings]
    text = "\n".join(out) + "\n"
    print(text)
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
        f.write(text)


def main():
    with open(os.path.join(HERE, "config.json"), encoding="utf-8") as f:
        config = json.load(f)

    tasks = collect(config["continents"])
    if not tasks:
        raise SystemExit("The API returned no hearts.")
    maps, trails, report = build(tasks, config, ground.load(os.path.join(HERE, "heights")))
    write_output(maps, trails)
    write_summary(tasks, maps, trails, report)


if __name__ == "__main__":
    main()
