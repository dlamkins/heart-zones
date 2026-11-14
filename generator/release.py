import argparse
import datetime
import glob
import os
import re
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_FILES = ["_markerCategories.xml", "boundary.png"]
TRAIL_LINE = re.compile(r'mapId="(\d+)" trailData="trails\\((\d+)(?:_\d+)?\.trl)"[^>]*/><!-- (.*) -->')
MAP_NAME = re.compile(r"<OverlayData><POIs><!-- (.*) -->")
ATTRIBUTE = re.compile(r'(\w+)="([^"]*)"')


def collect_package():
    files = {}
    paths = [os.path.join(ROOT, n) for n in STATIC_FILES]
    paths += glob.glob(os.path.join(ROOT, "map*.xml")) + glob.glob(os.path.join(ROOT, "trails", "*.trl"))
    for path in paths:
        with open(path, "rb") as f:
            files[os.path.relpath(path, ROOT).replace(os.sep, "/")] = f.read()
    return files


def write_taco(files, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=(2000, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, files[name])


def read_taco(path):
    if not os.path.exists(path):
        return {}
    with zipfile.ZipFile(path) as z:
        return {n.replace("\\", "/"): z.read(n) for n in z.namelist() if not n.endswith(("/", "\\"))}


def normalized(files):
    return {n: d.replace(b"\r\n", b"\n") if n.endswith(".xml") else d for n, d in files.items()}


def hearts(files):
    result = {}
    for name, data in files.items():
        if not re.fullmatch(r"map\d+\.xml", name):
            continue
        text = data.decode("utf-8")
        map_name = MAP_NAME.search(text)[1]
        for line in text.splitlines():
            m = TRAIL_LINE.search(line)
            if not m:
                continue
            heart = result.setdefault(int(m.group(3)), {"map": map_name, "objective": m.group(4), "content": []})
            attrs = tuple(sorted(ATTRIBUTE.findall(line.split("<!--")[0])))
            heart["content"].append((attrs, files.get(f"trails/{m.group(2)}")))
    return result


def release_notes(old, new):
    old_hearts, new_hearts = hearts(old), hearts(new)
    added = sorted(new_hearts.keys() - old_hearts.keys())
    removed = sorted(old_hearts.keys() - new_hearts.keys())
    changed = sorted(t for t in new_hearts.keys() & old_hearts.keys()
                     if sorted(new_hearts[t]["content"], key=repr) != sorted(old_hearts[t]["content"], key=repr))
    other = sorted(n for n in set(new) | set(old)
                   if not n.startswith("trails/") and not re.fullmatch(r"map\d+\.xml", n)
                   and new.get(n) != old.get(n))

    lines = []
    for title, ids, source in (("Added", added, new_hearts), ("Changed", changed, new_hearts),
                               ("Removed", removed, old_hearts)):
        if ids:
            lines += [f"### {title} hearts ({len(ids)})", ""]
            lines += [f"- **{source[t]['map']}** — {source[t]['objective']} ({t})" for t in ids] + [""]
    if other:
        lines += ["### Other files changed", ""] + [f"- `{n}`" for n in other] + [""]
    return "\n".join(lines) or "No heart changes.\n"


def next_version(previous_tag, bump):
    m = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", previous_tag)
    if not m:
        return "1.0.0"
    major, minor, patch = map(int, m.groups())
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "patch":
        return f"{major}.{minor}.{patch + 1}"
    return f"{major}.{minor + 1}.0"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--notes", required=True)
    parser.add_argument("--previous", required=True)
    parser.add_argument("--previous-tag", default="")
    parser.add_argument("--bump", choices=["major", "minor", "patch"], default="minor")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    new = collect_package()
    old = read_taco(args.previous)
    write_taco(new, args.out)
    new, old = normalized(new), normalized(old)

    changed = new != old or args.force
    version = next_version(args.previous_tag, args.bump)
    title = f"{version} - {datetime.datetime.now(datetime.timezone.utc):%Y-%m-%d}"
    notes = release_notes(old, new)
    with open(args.notes, "w", encoding="utf-8") as f:
        f.write(notes)

    print(notes)
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
        f.write(f"changed={'true' if changed else 'false'}\nversion={version}\ntitle={title}\n")


if __name__ == "__main__":
    main()
