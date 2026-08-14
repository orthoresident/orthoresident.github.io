"""
extract_labs.py
----------------
Extracts structured lab-result data from the HIS "investigations" HTML page
(result.txt) into clean Python objects / JSON / CSV.

Why regex instead of BeautifulSoup?
The page is NOT valid nested HTML: it stitches together many mini "sub
documents" that each re-open their own <head><html><body> tags inside the
outer page (one such fragment per lab panel), and it also embeds a second,
hidden copy of every panel (idata='..._grid', style='display:none') used
only for a JS grid view. A real HTML parser fixes/collapses this broken
markup in ways that scramble which <span> belongs to which row, so plain
text splitting + regex on known, stable markers is actually more reliable
here. This mirrors the approach already used in orthopedic_labs_fixed.py
for the HIS scraper (extracting unit/normal range from surrounding
context rather than trusting fixed structure).

Usage:
    python3 extract_labs.py result.txt out.json out.csv
"""
import re
import json
import csv
import sys
from datetime import datetime


def parse_dt(s):
    """Group datetime strings look like '19/4/2026 8:31 PM' (d/m/Y H:M AM/PM)."""
    try:
        return datetime.strptime(s.strip(), "%d/%m/%Y %I:%M %p")
    except (ValueError, AttributeError):
        return None


# Friendly name -> exact test name(s) as they appear on the HIS page.
# "Virology" maps to both HCV and HIV since that's the panel's content.
WANTED_TESTS = {
    "Hemoglobin": ["HGB"],
    "Platelets": ["PLT"],
    "INR": ["INR"],
    "S. Albumin": ["Serum Albumin"],
    "S. Creatinine": ["Creatinine"],
    "SGOT": ["SGOT(AST)"],
    "SGPT": ["SGPT(ALT)"],
    "Virology": ["Anti - HCV", "Anti - HIV", "HBs Ag"],
    "Blood Group": ["Blood Group", "RH factor"],
}


def filter_wanted(latest_rows):
    """Keep only the requested tests, drop doctor, relabel with friendly names."""
    by_exact_name = {row["test"]: row for row in latest_rows}

    # Blood Group + RH factor are two separate HIS rows but one clinical
    # value (e.g. "B" + "Positive" -> "B+"), so merge them into one row.
    out = []
    bg = by_exact_name.get("Blood Group")
    rh = by_exact_name.get("RH factor")
    if bg:
        sign = None
        if rh:
            sign = "+" if rh["value"].strip().lower().startswith("pos") else "-"
        out.append({
            "test": "Blood Group",
            "value": (bg["value"].strip() + sign) if sign else bg["value"],
            "unit": "",
            "normal_range": "",
            "datetime": bg["datetime"],
        })

    for friendly, exact_names in WANTED_TESTS.items():
        if friendly == "Blood Group":
            continue  # handled above
        for exact in exact_names:
            row = by_exact_name.get(exact)
            if row:
                out.append({
                    "test": friendly if len(exact_names) == 1 else "{0} ({1})".format(friendly, exact),
                    "value": row["value"],
                    "unit": row["unit"],
                    "normal_range": row["normal_range"],
                    "datetime": row["datetime"],
                })
    return out
    """
    Given flat rows (one per test result, each tagged with its panel
    datetime), keep only the most recent result for each distinct test name.
    If a datetime can't be parsed, that row is ignored when a comparable
    (parsed) result for the same test exists; otherwise it's kept as-is.
    """
    best = {}
    for row in rows:
        name = row["test"]
        dt = parse_dt(row["datetime"])
        row = dict(row, _dt=dt)
        current = best.get(name)
        if current is None:
            best[name] = row
            continue
        if dt is None:
            continue  # can't compare; keep whatever we already have
        if current["_dt"] is None or dt > current["_dt"]:
            best[name] = row
    # drop the helper key and return in a stable order
    return [
        {k: v for k, v in row.items() if k != "_dt"}
        for row in sorted(best.values(), key=lambda r: r["test"])
    ]


def latest_per_test(rows):
    """
    Given flat rows (one per test result, each tagged with its panel
    datetime), keep only the most recent result for each distinct test name.
    If a datetime can't be parsed, that row is ignored when a comparable
    (parsed) result for the same test exists; otherwise it's kept as-is.
    """
    best = {}
    for row in rows:
        name = row["test"]
        dt = parse_dt(row["datetime"])
        row = dict(row, _dt=dt)
        current = best.get(name)
        if current is None:
            best[name] = row
            continue
        if dt is None:
            continue
        if current["_dt"] is None or dt > current["_dt"]:
            best[name] = row
    return [
        {k: v for k, v in row.items() if k != "_dt"}
        for row in sorted(best.values(), key=lambda r: r["test"])
    ]


def parse_not_done(not_done_html):
    """Investigations requested but not yet performed."""
    # [^<]*? keeps this from swallowing the "<u>...</u>" section header above
    # the list, which also starts with a <b> tag.
    items = re.findall(r"<b>([^<]*?), requested at (.*?)</span>", not_done_html)
    return [{"test": name.strip(", "), "requested_at": dt.strip()} for name, dt in items]


def parse_done(done_html):
    """
    Investigations that were requested and completed, grouped by panel
    (e.g. CBC, Chemistry Group, Coagulation Profile...).
    """
    # Each REAL result panel is wrapped in:
    #   <div class='invs' style='overflow:auto;' idata='<code>,_form' ...>
    # The page also contains a second, hidden, duplicate copy of each panel
    # for its JS grid-view (idata='<code>_grid', style='display:none;...'),
    # which we must exclude or every result would be counted twice.
    raw_chunks = done_html.split("<div class='invs'")
    chunks = [c for c in raw_chunks
              if re.match(r"\s*style='overflow:auto;'\s*idata='[^']*,_form'", c)]

    groups = []
    for chunk in chunks:
        header = re.search(r"<b>(.*?),,?\s*(\d.*?)</span>", chunk)
        group_name = header.group(1).strip(", ") if header else None
        group_datetime = header.group(2).strip() if header else None

        tests, comment, doctor = [], None, None

        # Rows are delimited by <tr> inside the panel's <table>
        for row in re.split(r"<tr>", chunk):
            if "test_id='comment" in row:
                m = re.search(r"color:black;'\s*id='.*?'>(.*?)<", row, re.S)
                if m:
                    comment = m.group(1).strip()
                continue
            if "test_id='doctor" in row:
                m = re.search(r"color:black;'\s*id='.*?'>(.*?)</span>", row, re.S)
                if m:
                    doctor = m.group(1).strip()
                continue

            m = re.search(
                r"test_id='(?P<test_id>.*?)'"          # internal test code
                r".*?<b>(?P<name>.*?)</span>"           # test name
                r".*?color:black;'\s*>(?P<value>.*?)</span>"  # result value
                r"(?P<unit_html>.*?)<td>"               # unit (may contain span/nbsp junk)
                r".*?_normal'>(?P<normal>.*?)(?:<br|$)",  # reference/normal range
                row, re.S,
            )
            if not m:
                continue  # row without a real test (e.g. table header row)

            unit = re.sub(r"<.*?>", "", m.group("unit_html")).replace("&nbsp", "").strip()
            tests.append({
                "test_id": m.group("test_id"),
                "name": m.group("name").strip(),
                "value": m.group("value").strip(),
                "unit": unit,
                "normal_range": m.group("normal").strip(),
            })

        groups.append({
            "group": group_name,
            "datetime": group_datetime,
            "doctor": doctor,
            "comment": comment,
            "tests": tests,
        })
    return groups


def parse_result_page(html_text):
    not_done_html, _, done_html = html_text.partition(
        "Investigations which are requested and done"
    )
    return {
        "not_done": parse_not_done(not_done_html),
        "done": parse_done(done_html),
    }


def to_flat_rows(parsed):
    """Flatten into one row per test result, handy for CSV / pandas."""
    rows = []
    for g in parsed["done"]:
        for t in g["tests"]:
            rows.append({
                "group": g["group"],
                "datetime": g["datetime"],
                "doctor": g["doctor"],
                "test": t["name"],
                "value": t["value"],
                "unit": t["unit"],
                "normal_range": t["normal_range"],
            })
    return rows


if __name__ == "__main__":
    in_path = sys.argv[1] if len(sys.argv) > 1 else "result.txt"
    json_out = sys.argv[2] if len(sys.argv) > 2 else "out.json"
    csv_out = sys.argv[3] if len(sys.argv) > 3 else "out.csv"

    with open(in_path, encoding="utf-8") as f:
        html_text = f.read()

    parsed = parse_result_page(html_text)

    with open(json_out, "w", encoding="utf-8") as f:
        json.dump(parsed, f, ensure_ascii=False, indent=2)

    rows = to_flat_rows(parsed)
    latest_rows = latest_per_test(rows)
    wanted_rows = filter_wanted(latest_rows)

    with open(csv_out, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["group", "datetime", "doctor", "test", "value", "unit", "normal_range"])
        writer.writeheader()
        writer.writerows(rows)

    wanted_json_out = json_out.replace(".json", "_wanted.json")
    wanted_csv_out = csv_out.replace(".csv", "_wanted.csv")
    with open(wanted_json_out, "w", encoding="utf-8") as f:
        json.dump(wanted_rows, f, ensure_ascii=False, indent=2)
    with open(wanted_csv_out, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["test", "value", "unit", "normal_range", "datetime"])
        writer.writeheader()
        writer.writerows(wanted_rows)

    print("Not-done investigations:", len(parsed["not_done"]))
    print("Completed panels:", len(parsed["done"]))
    print("Total individual test results:", len(rows))
    print("Requested tests found:", len(wanted_rows), "of", len(WANTED_TESTS))
    print("Wrote:", json_out, csv_out, wanted_json_out, wanted_csv_out)
