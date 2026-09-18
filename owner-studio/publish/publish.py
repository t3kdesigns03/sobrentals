#!/usr/bin/env python3
"""
SOB Rentals — Owner Studio publish transform.

This one script handles every approved draft. The action is chosen by the
manifest's "action" field:

  "add"           (default) — a brand-new unit:
        1. detects the target community's existing conventions from the nearest
           sibling (folder-name pattern, detail-filename pattern, img001 vs 001)
        2. resizes/compresses photos (max edge 2000px, jpeg; rejects >10MB
           originals that still won't compress under 10MB)
        3. writes Properties/<Community>/<UnitFolder>/<001..>.jpeg
        4. clones the nearest sibling detail page into a new detail .html
        5. inserts ONE card into Properties/<Community>/properties.html
           (skipped if the unit name contains TEST)
        6. best-effort appends an entry to the root properties.json

  "change_cover"  — an existing unit: repoint the display/cover photo to the one
        Sheila chose. Updates the detail page (moves the chosen photo to the
        front of propertyImages + preload), the collection card, the root card,
        and the apex index feature card — everywhere that unit's cover shows.

  "remove"        — an existing SOLD unit: unlist it. Removes the unit's card
        from the collection page, the root properties page, and the apex index
        feature (plus its <option> in the apex dropdown). The detail page and
        photo folder are LEFT in the repo (recoverable), matching how sold units
        were retired before.

It is the SAME script the Approve GitHub Action runs, and it can be run locally
with no secrets/network to verify a draft end-to-end.

Usage:
  publish.py --repo <repo_root> --manifest <path/to/manifest.json> [--photos-dir DIR]
             [--no-card] [--dry-run]
"""
import argparse, json, os, re, sys, glob, shutil
from pathlib import Path

COMMUNITIES = ["Breakwater_Bay","Compass_Point","Golden_Reef","Grandview_Point",
  "Harbor_Point","Heron_Bay","Houses","Indian_Point","Lands_End_Condos","Ledges",
  "Palisades","Parkside_Place","Robins_Resort","SouthwoodShores","The_Knolls"]

MAX_EDGE = 2000
JPEG_Q = 82
TEN_MB = 10 * 1024 * 1024

def log(*a): print("[publish]", *a)

def community_label(c): return c.replace("_", " ")

def slug_unit(u):
    return re.sub(r"[^a-z0-9]+", "-", u.strip().lower()).strip("-")

def enc_path(p):
    """Match the site's URL encoding: spaces -> %20, parens left as-is."""
    return p.replace(" ", "%20")

# ---- folder-name pattern parsing (returns beds, sleeps, unitid + spans) ----
FOLDER_PATTERNS = [
    re.compile(r"(?i)^(?P<beds>\d+)\s*bedroom\s*-\s*sleeps\s*(?P<sleeps>\d+)\s*-\s*(?:unit\s+)?(?P<unitid>\S.*?)\s*$"),
    re.compile(r"(?i)^(?P<beds>\d+)\s*bedroom\s*-\s*(?:unit\s+)?(?P<unitid>.+?)\s*\(\s*sleeps\s*(?P<sleeps>\d+)\s*\)\s*$"),
    re.compile(r"(?i)^(?P<beds>\d+)\s*bedroom\s*\(\s*sleeps\s*(?P<sleeps>\d+)\s*\)\s*-\s*(?:unit\s+)?(?P<unitid>\S.*?)\s*$"),
]
DETAIL_PATTERN = re.compile(r"(?i)^(?P<beds>\d+)-bedroom-sleeps-(?P<sleeps>\d+)-(?P<unitpfx>unit-)?(?P<unitid>.+)\.html?$")

def parse_folder(name):
    for pat in FOLDER_PATTERNS:
        m = pat.match(name)
        if m:
            return {"beds": int(m["beds"]), "sleeps": int(m["sleeps"]),
                    "unitid": m["unitid"].strip(), "match": m, "name": name}
    return None

def span_replace(s, m, repls):
    """repls: dict group_name -> new string. Apply by span, right to left."""
    items = []
    for g, val in repls.items():
        try:
            span = m.span(g)
        except Exception:
            continue
        if span[0] < 0: continue
        items.append((span, str(val)))
    for (a, b), val in sorted(items, key=lambda x: -x[0][0]):
        s = s[:a] + val + s[b:]
    return s

def img_prefix_of(folder_path):
    files = sorted(glob.glob(os.path.join(folder_path, "*")))
    for f in files:
        b = os.path.basename(f).lower()
        if re.match(r"^img\d+\.jpe?g$", b): return "img"
        if re.match(r"^\d+\.jpe?g$", b): return ""
    return ""

def pick_sibling(comm_dir, beds, sleeps):
    """nearest existing unit folder: prefer same beds, then closest sleeps."""
    sibs = []
    for entry in sorted(os.listdir(comm_dir)):
        p = os.path.join(comm_dir, entry)
        if not os.path.isdir(p): continue
        info = parse_folder(entry)
        if info:
            info["path"] = p
            sibs.append(info)
    if not sibs:
        return None
    sibs.sort(key=lambda s: (s["beds"] != beds, abs(s["sleeps"] - sleeps), abs(s["beds"] - beds)))
    return sibs[0]

def find_detail_file(comm_dir, sib):
    """find the sibling's detail .html by matching beds/sleeps/unitid."""
    cands = []
    for f in glob.glob(os.path.join(comm_dir, "*.htm")) + glob.glob(os.path.join(comm_dir, "*.html")):
        b = os.path.basename(f)
        if b.lower() in ("properties.html",): continue
        m = DETAIL_PATTERN.match(b)
        if not m: continue
        cands.append((b, m, f))
    # exact unit match first
    for b, m, f in cands:
        if m["unitid"].strip().lower() == sib["unitid"].strip().lower() \
           and int(m["beds"]) == sib["beds"] and int(m["sleeps"]) == sib["sleeps"]:
            return (b, m, f)
    # else same beds+sleeps
    for b, m, f in cands:
        if int(m["beds"]) == sib["beds"] and int(m["sleeps"]) == sib["sleeps"]:
            return (b, m, f)
    # else any
    return cands[0] if cands else None

# ---------- image processing ----------
def process_photo(src, dst):
    """Resize to <=MAX_EDGE, save jpeg. Returns True, or False if rejected."""
    from PIL import Image, ImageOps
    orig_size = os.path.getsize(src)
    try:
        im = Image.open(src)
        im = ImageOps.exif_transpose(im)
        if im.mode not in ("RGB",):
            im = im.convert("RGB")
        w, h = im.size
        scale = min(1.0, MAX_EDGE / float(max(w, h)))
        if scale < 1.0:
            im = im.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
        im.save(dst, "JPEG", quality=JPEG_Q, optimize=True, progressive=True)
    except Exception as e:
        log("  !! could not process", os.path.basename(src), "-", e)
        return False
    if orig_size > TEN_MB and os.path.getsize(dst) > TEN_MB:
        log("  !! REJECTED (>10MB, would not compress):", os.path.basename(src))
        try: os.remove(dst)
        except OSError: pass
        return False
    return True

def html_escape(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

# ---------- detail page ----------
def build_detail(sib_text, ctx):
    t = sib_text
    if ctx.get("sib_folder"):
        t = t.replace(ctx["sib_folder"], ctx["folder"])  # fix stray alt/refs to the sibling folder
    label, unit, beds, baths, sleeps = ctx["label"], ctx["unit"], ctx["beds"], ctx["baths"], ctx["sleeps"]
    n, folder, prefix = ctx["n"], ctx["folder"], ctx["prefix"]
    sib_unit = ctx["sib_unitid"]
    S = re.S

    # noun (Condo/House/Home) from sibling title
    mnoun = re.search(r"·\s*\d+\s*Bedroom\s+([A-Za-z]+)\s*#", sib_text)
    noun = mnoun.group(1) if mnoun else ("Home" if ctx["community"] == "Houses" else "Condo")
    heading = f"{label} · {beds} Bedroom {noun} #{unit}"

    # propertyImages array (raw folder — unchanged from the verified add path)
    arr = ",\n      ".join('"%s/%s%03d.jpeg"' % (folder, prefix, i) for i in range(1, n + 1))
    t = re.sub(r"window\.propertyImages\s*=\s*\[.*?\];",
               "window.propertyImages = [\n      " + arr + "\n    ];", t, flags=S)
    # preload
    t = re.sub(r'(<link[^>]+rel="preload"[^>]+href=")[^"]*(")',
               lambda m: m.group(1) + f"{folder}/{prefix}001.jpeg" + m.group(2), t, count=1)
    # title
    t = re.sub(r"<title>.*?</title>",
               f"<title>{heading.replace(chr(183),'·')} (Sleeps {sleeps}) | SOB Rentals</title>", t, flags=S)
    # meta description
    t = re.sub(r'(<meta name="description" content=")[^"]*(")',
               lambda m: m.group(1) + f"{label} {beds} bedroom #{unit} at Lake of the Ozarks. Sleeps {sleeps}." + m.group(2), t, count=1)
    # H1 headings (mobile + desktop)
    t = re.sub(r'(<h1 class="font-serif text-xl font-bold text-white mb-0\.5">).*?(</h1>)',
               lambda m: m.group(1) + heading + m.group(2), t, flags=S)
    t = re.sub(r'(<h1 class="font-serif text-5xl md:text-6xl font-bold mb-2">).*?(</h1>)',
               lambda m: m.group(1) + heading + m.group(2), t, flags=S)
    # desktop subtitle
    t = re.sub(r'(<p class="text-xl opacity-90">).*?(</p>)',
               lambda m: m.group(1) + f"Lake of the Ozarks · {label} · Sleeps {sleeps}" + m.group(2), t, count=1, flags=S)
    # stat tiles
    t = re.sub(r'(<p class="font-semibold">)Sleeps \d+(</p>)', lambda m: m.group(1) + f"Sleeps {sleeps}" + m.group(2), t)
    t = re.sub(r'(<p class="font-semibold">)\d+ Bedrooms?(</p>)',
               lambda m: m.group(1) + f"{beds} Bedroom" + ("s" if beds > 1 else "") + m.group(2), t)
    t = re.sub(r'(<p class="font-semibold">)\d+ Bathrooms?(</p>)',
               lambda m: m.group(1) + f"{baths} Bathroom" + ("s" if baths > 1 else "") + m.group(2), t)
    # photos heading
    t = re.sub(r">All \d+ Photos<", f">All {n} Photos<", t)
    # about paragraph (use description if provided)
    if ctx["description"]:
        t = re.sub(r'(<p class="text-lg text-gray-600 leading-relaxed mb-4">).*?(</p>)',
                   lambda m: m.group(1) + html_escape(ctx["description"]) + m.group(2), t, count=1, flags=S)
    # max guests
    t = re.sub(r"Max guests:\s*\d+", f"Max guests: {sleeps}", t)
    # book subject
    t = re.sub(r"(const subject = ')[^']*(';)", lambda m: m.group(1) + f"Book {label} {unit}" + m.group(2), t)
    # vrbo/booking link
    if ctx["sourceUrl"]:
        t = re.sub(r'(href=")https?://(?:www\.)?(?:vrbo|airbnb)\.com/[^"]*(")',
                   lambda m: m.group(1) + ctx["sourceUrl"] + m.group(2), t, count=1)
    # targeted alt / label references
    if sib_unit:
        t = t.replace(f"{label} {sib_unit}", f"{label} {unit}")
        t = t.replace(f"#{sib_unit}", f"#{unit}")
        t = t.replace(f"{sib_unit} condo", f"{unit} condo").replace(f"{sib_unit} Condo", f"{unit} Condo")
    return t

# ---------- card location / extraction (shared by add / cover / remove) ----------
def extract_first_card(html):
    start = html.find('<div class="property-card')
    if start < 0: return (None, None, None)
    depth = 0
    for m in re.finditer(r"</?div\b", html[start:], re.I):
        if m.group().lower().startswith("</"):
            depth -= 1
            if depth == 0:
                end = html.find(">", start + m.end()) + 1
                return (start, end, html[start:end])
        else:
            depth += 1
    return (None, None, None)

def card_span_containing(html, needle):
    """Return (start, end) of the <div class="property-card"> block whose HTML
    contains `needle` (e.g. the unit's detail filename). None if not found."""
    ni = html.find(needle)
    if ni < 0:
        # case-insensitive fallback
        low = html.lower(); nl = needle.lower()
        ni = low.find(nl)
        if ni < 0:
            return None
    start = html.rfind('<div class="property-card', 0, ni + len(needle))
    if start < 0:
        return None
    depth = 0
    for m in re.finditer(r"</?div\b", html[start:], re.I):
        if m.group().lower().startswith("</"):
            depth -= 1
            if depth == 0:
                end = html.find(">", start + m.end()) + 1
                # sanity: the needle must actually be inside this card
                if start <= ni < end:
                    return (start, end)
                return None
        else:
            depth += 1
    return None

def expand_removal_span(html, start, end):
    """Grow (start,end) to also swallow a preceding HTML comment (e.g.
    <!-- 10210 -->) and the blank whitespace around the card, so removal leaves
    no dangling comment or double blank lines."""
    # include a preceding comment line if it sits just above the card
    pre = html[:start]
    mcomment = re.search(r"[ \t]*<!--[^>]*-->[ \t]*\n(\s*)$", pre)
    if mcomment:
        start = mcomment.start()
    # trim one trailing newline block after the card
    after = html[end:]
    mws = re.match(r"[ \t]*\n\s*\n", after)
    if mws:
        end = end + mws.end() - 1  # keep a single newline
    else:
        mws = re.match(r"[ \t]*\n", after)
        if mws:
            end = end + mws.end()
    # also drop leading whitespace on the card's own line
    ls = html.rfind("\n", 0, start)
    if ls >= 0 and html[ls + 1:start].strip() == "":
        start = ls + 1
    return start, end

def set_card_cover(card_html, new_src):
    """Replace the first <img ... src="..."> in a card with new_src."""
    return re.sub(r'(<img\b[^>]*\bsrc=")[^"]*(")',
                  lambda m: m.group(1) + new_src + m.group(2), card_html, count=1)

# ---------- card build (add) ----------
def build_card(sib_card, ctx):
    label, unit, beds, sleeps = ctx["label"], ctx["unit"], ctx["beds"], ctx["sleeps"]
    folder, prefix, new_detail = ctx["folder"], ctx["prefix"], ctx["new_detail"]
    c = sib_card
    has_unit = bool(re.search(r"-\s*unit\s+", sib_card, re.I))
    # cover image
    c = re.sub(r'(<img[^>]+src=")[^"]*(")', lambda m: m.group(1) + f"{folder}/{prefix}001.jpeg" + m.group(2), c, count=1)
    c = re.sub(r'(<img[^>]+alt=")[^"]*(")', lambda m: m.group(1) + f"{label} #{unit} - {beds}BR sleeps {sleeps}" + m.group(2), c, count=1)
    # title
    h4 = f"{beds} Bedroom (Sleeps {sleeps}) - " + ("Unit " if has_unit else "") + unit
    c = re.sub(r"(<h4[^>]*>).*?(</h4>)", lambda m: m.group(1) + h4 + m.group(2), c, count=1, flags=re.S)
    # bed + sleeps spans
    c = re.sub(r"(<span>)\d+ Bed(</span>)", lambda m: m.group(1) + f"{beds} Bed" + m.group(2), c, count=1)
    c = re.sub(r"(<span>)Sleeps \d+(</span>)", lambda m: m.group(1) + f"Sleeps {sleeps}" + m.group(2), c, count=1)
    # detail link (the View Details anchor)
    c = re.sub(r'(<a href=")\.?/?[^"]*\.html(")', lambda m: m.group(1) + f"./{new_detail}" + m.group(2), c, count=1)
    return c

def insert_card(props_text, new_card):
    gm = re.search(r'<div class="grid[^"]*properties-grid[^"]*">', props_text)
    block = "\n                " + new_card
    if gm:
        i = gm.end()
        return props_text[:i] + block + props_text[i:]
    start, end, _ = extract_first_card(props_text)
    if start is not None:
        return props_text[:start] + new_card + "\n                " + props_text[start:]
    return props_text  # give up silently

# ---------- properties.json ----------
def append_json(repo, ctx):
    jp = os.path.join(repo, "properties.json")
    if not os.path.exists(jp): return
    try:
        data = json.load(open(jp, encoding="utf-8"))
        vrbo = ""
        m = re.search(r"vrbo\.com/(\d+)", ctx["sourceUrl"] or "")
        if m: vrbo = m.group(1)
        entry = {
            "id": slug_unit(f'{ctx["community"]}-{ctx["unit"]}'),
            "collection": ctx["label"], "unit": ctx["unit"],
            "name": f'{ctx["label"]} {ctx["unit"]}',
            "beds": ctx["beds"], "baths": ctx["baths"], "sleeps": ctx["sleeps"],
            "vrbo": vrbo,
            "page": f'Properties/{ctx["community"]}/{ctx["new_detail"]}',
            "cover": f'Properties/{ctx["community"]}/{ctx["folder"]}/{ctx["prefix"]}001.jpeg',
        }
        data.setdefault("properties", []).insert(0, entry)
        data["count"] = len(data["properties"])
        json.dump(data, open(jp, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
        log("  properties.json updated (count=%d)" % data["count"])
    except Exception as e:
        log("  (properties.json not updated:", e, ")")

def remove_json(repo, community, unit):
    jp = os.path.join(repo, "properties.json")
    if not os.path.exists(jp): return
    try:
        data = json.load(open(jp, encoding="utf-8"))
        want = slug_unit(f"{community}-{unit}")
        before = len(data.get("properties", []))
        data["properties"] = [p for p in data.get("properties", []) if p.get("id") != want]
        if len(data["properties"]) != before:
            data["count"] = len(data["properties"])
            json.dump(data, open(jp, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
            log("  properties.json entry removed (count=%d)" % data["count"])
    except Exception as e:
        log("  (properties.json not updated:", e, ")")

def set_json_cover(repo, community, unit, cover_rel):
    jp = os.path.join(repo, "properties.json")
    if not os.path.exists(jp): return
    try:
        data = json.load(open(jp, encoding="utf-8"))
        want = slug_unit(f"{community}-{unit}")
        for p in data.get("properties", []):
            if p.get("id") == want:
                p["cover"] = cover_rel
                json.dump(data, open(jp, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
                log("  properties.json cover updated")
                return
    except Exception as e:
        log("  (properties.json not updated:", e, ")")

# ---------- resolve an existing unit from a manifest (cover/remove) ----------
def resolve_unit(repo, community, folder):
    """Given community + unit folder name, find its detail file + parsed specs."""
    comm_dir = os.path.join(repo, "Properties", community)
    info = parse_folder(folder)
    if not info:
        log("FATAL: could not parse unit folder:", repr(folder)); sys.exit(1)
    det = find_detail_file(comm_dir, info)
    if not det:
        log("FATAL: no detail .html found for", folder); sys.exit(1)
    det_name, det_m, det_path = det
    return {"comm_dir": comm_dir, "folder": folder, "info": info,
            "detail_name": det_name, "detail_path": det_path,
            "unitid": info["unitid"], "beds": info["beds"], "sleeps": info["sleeps"]}

def rewrite(path, old, new, dry_run):
    if old == new:
        return False
    if dry_run:
        return True
    open(path, "w", encoding="utf-8", newline="\n").write(new)
    return True

# ---------- ACTION: change_cover ----------
def do_change_cover(repo, man, dry_run):
    community = man["community"]
    folder = man["folder"]
    cover = os.path.basename(str(man.get("coverPhoto") or "").strip())
    if not cover:
        log("FATAL: change_cover needs coverPhoto"); sys.exit(1)
    u = resolve_unit(repo, community, folder)
    label = community_label(community)
    enc_folder = enc_path(folder)
    coll_src = f"{enc_folder}/{cover}"                                  # collection page (folder-relative)
    root_src = f"Properties/{community}/{enc_folder}/{cover}"           # root + apex (repo-relative)
    changed = []

    # 1) detail page — move chosen photo to propertyImages[0] + preload
    dp = u["detail_path"]
    t = open(dp, encoding="utf-8", errors="replace").read()
    m = re.search(r"(window\.propertyImages\s*=\s*\[)(.*?)(\];)", t, re.S)
    if not m:
        log("  !! detail page has no propertyImages array — skipped")
    else:
        entries = re.findall(r"'([^']*)'|\"([^\"]*)\"", m.group(2))
        entries = [a or b for (a, b) in entries]
        idx = next((i for i, e in enumerate(entries) if os.path.basename(e) == cover), -1)
        if idx < 0:
            # not in array (shouldn't happen) — prepend it
            entries.insert(0, coll_src)
        else:
            entries.insert(0, entries.pop(idx))
        arr = ",\n      ".join('"%s"' % e for e in entries)
        new_block = m.group(1) + "\n      " + arr + "\n    " + m.group(3)
        t2 = t[:m.start()] + new_block + t[m.end():]
        # preload (optional)
        t2 = re.sub(r'(<link[^>]+rel="preload"[^>]+href=")[^"]*(")',
                    lambda mm: mm.group(1) + coll_src + mm.group(2), t2, count=1)
        if rewrite(dp, t, t2, dry_run):
            changed.append(os.path.relpath(dp, repo))

    # 2) collection page card
    cp = os.path.join(u["comm_dir"], "properties.html")
    if os.path.exists(cp):
        ct = open(cp, encoding="utf-8", errors="replace").read()
        span = card_span_containing(ct, u["detail_name"])
        if span:
            s, e = span
            new_card = set_card_cover(ct[s:e], coll_src)
            nt = ct[:s] + new_card + ct[e:]
            if rewrite(cp, ct, nt, dry_run):
                changed.append(os.path.relpath(cp, repo))
        else:
            log("  (collection card not found — skipped)")

    # 3) root properties.html + 4) apex index.html
    for rel in ("properties.html", "index.html"):
        fp = os.path.join(repo, rel)
        if not os.path.exists(fp): continue
        ft = open(fp, encoding="utf-8", errors="replace").read()
        needle = f"Properties/{community}/{u['detail_name']}"
        span = card_span_containing(ft, needle) or card_span_containing(ft, u["detail_name"])
        if span:
            s, e = span
            new_card = set_card_cover(ft[s:e], root_src)
            nt = ft[:s] + new_card + ft[e:]
            if rewrite(fp, ft, nt, dry_run):
                changed.append(rel)
        # else: unit isn't featured here — normal, skip quietly

    # 5) properties.json cover (best-effort)
    if not dry_run:
        set_json_cover(repo, community, u["unitid"], root_src)

    log("change_cover:", label, u["unitid"], "-> cover", cover)
    log("  files changed:", ", ".join(changed) if changed else "(none)")
    if not changed:
        log("FATAL: nothing was changed — cover photo not found in any location"); sys.exit(1)

# ---------- ACTION: remove (unlist) ----------
def do_remove(repo, man, dry_run):
    community = man["community"]
    folder = man["folder"]
    u = resolve_unit(repo, community, folder)
    label = community_label(community)
    changed = []

    def strip_card(fp, needles):
        if not os.path.exists(fp): return
        ft = open(fp, encoding="utf-8", errors="replace").read()
        span = None
        for nd in needles:
            span = card_span_containing(ft, nd)
            if span: break
        if not span:
            return  # unit not listed here
        s, e = span
        s, e = expand_removal_span(ft, s, e)
        nt = ft[:s] + ft[e:]
        if rewrite(fp, ft, nt, dry_run):
            changed.append(os.path.relpath(fp, repo))

    # 1) collection page (folder-relative detail href)
    strip_card(os.path.join(u["comm_dir"], "properties.html"), [u["detail_name"]])
    # 2) root properties.html + 3) apex index.html (repo-relative detail href)
    for rel in ("properties.html", "index.html"):
        strip_card(os.path.join(repo, rel),
                   [f"Properties/{community}/{u['detail_name']}", u["detail_name"]])

    # 4) apex dropdown <option> (best-effort): match "<Label> <unit>"
    apex = os.path.join(repo, "index.html")
    if os.path.exists(apex):
        at = open(apex, encoding="utf-8", errors="replace").read()
        opt_re = re.compile(r"[ \t]*<option[^>]*>\s*" + re.escape(label) + r"\s+" +
                            re.escape(u["unitid"]) + r"\b[^<]*</option>\s*\n?", re.I)
        nt = opt_re.sub("", at, count=1)
        if rewrite(apex, at, nt, dry_run) and "index.html" not in changed:
            changed.append("index.html")

    # 5) properties.json (best-effort)
    if not dry_run:
        remove_json(repo, community, u["unitid"])

    log("remove (unlist):", label, u["unitid"], "(detail page + photos kept)")
    log("  files changed:", ", ".join(changed) if changed else "(none)")
    if not changed:
        log("FATAL: unit was not listed anywhere — nothing removed"); sys.exit(1)

# ---------- ACTION: add ----------
def do_add(repo, man, args):
    community = man["community"]
    if community not in COMMUNITIES:
        log("FATAL: unknown community", community); sys.exit(1)
    unit = str(man["unit"]).strip()
    beds = int(man.get("beds") or 1); baths = int(man.get("baths") or 1); sleeps = int(man.get("sleeps") or 2)
    label = community_label(community)

    photos_dir = args.photos_dir or os.path.join(os.path.dirname(os.path.abspath(args.manifest)), "photos")
    srcs = man.get("photos")
    if srcs:
        srcs = [os.path.join(repo, p) if not os.path.isabs(p) else p for p in srcs]
        srcs = [p for p in srcs if os.path.exists(p)]
    if not srcs:
        srcs = sorted(glob.glob(os.path.join(photos_dir, "*")))
    srcs = [p for p in srcs if re.search(r"\.(jpe?g|png|webp|heic|heif|tif?f)$", p, re.I)]
    if not srcs:
        log("FATAL: no photos found"); sys.exit(1)

    comm_dir = os.path.join(repo, "Properties", community)
    sib = pick_sibling(comm_dir, beds, sleeps)
    if not sib:
        log("FATAL: no sibling unit to model in", community); sys.exit(1)
    prefix = img_prefix_of(sib["path"])
    log("nearest sibling:", sib["name"], "| img prefix:", repr(prefix))

    folder = span_replace(sib["name"], sib["match"], {"beds": beds, "sleeps": sleeps, "unitid": unit})
    det = find_detail_file(comm_dir, sib)
    if not det:
        log("FATAL: no sibling detail .html in", community); sys.exit(1)
    sib_det_name, sib_det_m, sib_det_path = det
    new_detail = span_replace(sib_det_name, sib_det_m, {"beds": beds, "sleeps": sleeps, "unitid": slug_unit(unit)})
    log("new folder:", folder)
    log("new detail:", new_detail)

    ctx = {"community": community, "label": label, "unit": unit, "beds": beds,
           "baths": baths, "sleeps": sleeps, "title": man.get("title", ""),
           "description": man.get("description", ""), "sourceUrl": man.get("sourceUrl", ""),
           "folder": folder, "prefix": prefix, "new_detail": new_detail,
           "sib_unitid": sib["unitid"], "sib_folder": sib["name"]}

    # ---- images ----
    out_folder = os.path.join(comm_dir, folder)
    if not args.dry_run: os.makedirs(out_folder, exist_ok=True)
    kept = 0
    for i, src in enumerate(srcs):
        idx = kept + 1
        dst = os.path.join(out_folder, f"{prefix}{idx:03d}.jpeg")
        if args.dry_run:
            log("  would write", os.path.relpath(dst, repo)); kept += 1; continue
        if process_photo(src, dst): kept += 1
    if kept == 0:
        log("FATAL: all photos rejected"); sys.exit(1)
    ctx["n"] = kept
    log("photos written:", kept)

    # ---- detail page ----
    sib_text = open(sib_det_path, encoding="utf-8", errors="replace").read()
    detail_html = build_detail(sib_text, ctx)
    detail_path = os.path.join(comm_dir, new_detail)
    if args.dry_run:
        log("  would write detail", os.path.relpath(detail_path, repo))
    else:
        open(detail_path, "w", encoding="utf-8", newline="\n").write(detail_html)
    log("detail page written:", os.path.relpath(detail_path, repo))

    # ---- card ----
    is_test = "TEST" in unit.upper()
    if args.no_card or is_test:
        log("card SKIPPED", "(unit contains TEST)" if is_test else "(--no-card)")
    else:
        pp = os.path.join(comm_dir, "properties.html")
        ptext = open(pp, encoding="utf-8", errors="replace").read()
        _, _, sib_card = extract_first_card(ptext)
        if not sib_card:
            log("  !! no sibling card found; card NOT inserted")
        else:
            new_card = build_card(sib_card, ctx)
            updated = insert_card(ptext, new_card)
            if args.dry_run:
                log("  would insert card into", os.path.relpath(pp, repo))
            else:
                open(pp, "w", encoding="utf-8", newline="\n").write(updated)
            log("card inserted into", os.path.relpath(pp, repo))

    # ---- properties.json ----
    if not args.dry_run:
        append_json(repo, ctx)

    log("LIVE URL (after Pages deploys):",
        f'https://sobrentals.com/Properties/{community}/{new_detail}')

# ---------- main ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--photos-dir")
    ap.add_argument("--no-card", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    repo = os.path.abspath(args.repo)
    man = json.load(open(args.manifest, encoding="utf-8"))
    action = (man.get("action") or "add").strip()
    if man.get("community") not in COMMUNITIES:
        log("FATAL: unknown community", man.get("community")); sys.exit(1)

    if action == "add":
        do_add(repo, man, args)
    elif action == "change_cover":
        do_change_cover(repo, man, args.dry_run)
    elif action == "remove":
        do_remove(repo, man, args.dry_run)
    else:
        log("FATAL: unknown action", repr(action)); sys.exit(1)
    log("DONE.")

if __name__ == "__main__":
    main()
