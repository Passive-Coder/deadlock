import csv
import hashlib
import io
import json
from pathlib import Path
import random
import zipfile


def digest(data):
    return hashlib.sha256(data).hexdigest()


def dataset(seed):
    rng = random.Random(seed)
    return [{"id": i + 1, "region": ["North", "South", "East", "West"][i % 4], "amount": rng.randint(10, 200)} for i in range(60)]


def csv_bytes(rows):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode()


def summary(rows):
    return [{"region": region, "total": sum(r["amount"] for r in rows if r["region"] == region)}
            for region in sorted({r["region"] for r in rows})]


def validate(path: Path, kind, rows):
    try:
        raw = path.read_bytes()
        input_hash = digest(csv_bytes(rows))
        if kind == "summary":
            actual = list(csv.DictReader(io.StringIO(raw.decode())))
            valid = actual == [{k: str(v) for k, v in r.items()} for r in summary(rows)]
        elif kind == "report":
            text = raw.decode()
            valid = all(x in text for x in [input_hash, "Regional summary", "Dataset overview", f"data-total=\"{sum(r['amount'] for r in rows)}\""])
            valid = valid and all(f"<td>{r['region']}</td><td>{r['total']}</td>" in text for r in summary(rows))
        elif kind == "package":
            with zipfile.ZipFile(path) as archive:
                manifest = json.loads(archive.read("manifest.json"))
                valid = sorted(archive.namelist()) == ["dataset.csv", "manifest.json"]
                valid = valid and archive.read("dataset.csv") == csv_bytes(rows)
                valid = valid and manifest == {"input_sha256": input_hash, "rows": len(rows)}
        else:
            valid = json.loads(raw) == {"rows": len(rows), "total": sum(r["amount"] for r in rows)}
        return {"valid": bool(valid), "sha256": digest(raw), "size": len(raw), "error": None if valid else "Content validation failed"}
    except (OSError, ValueError, KeyError, zipfile.BadZipFile):
        return {"valid": False, "sha256": None, "size": 0, "error": "Output missing or corrupted"}


def publish(directory, worker, rows):
    suffix = {"summary": "csv", "report": "html", "package": "zip", "audit": "json"}[worker["kind"]]
    final = directory / f"{worker['id']}.{suffix}"
    temp = directory / f"{worker['id']}-{worker['attempt']}.tmp"
    kind = worker["kind"]
    if kind == "summary":
        temp.write_bytes(csv_bytes(summary(rows)))
    elif kind == "report":
        body = "".join(f"<tr><td>{r['region']}</td><td>{r['total']}</td></tr>" for r in summary(rows))
        temp.write_text(f'<!doctype html><html lang="en"><meta charset="utf-8"><title>Regional report</title>'
            f'<style>body{{font:16px system-ui;max-width:760px;margin:60px auto;padding:24px}}td,th{{padding:12px 40px 12px 0;text-align:left}}code{{overflow-wrap:anywhere}}</style>'
            f'<h1>Dataset overview</h1><p data-total="{sum(r["amount"] for r in rows)}">{len(rows)} verified records</p>'
            f'<h2>Regional summary</h2><table><tr><th>Region</th><th>Total</th></tr>{body}</table>'
            f'<p>Input SHA-256: <code>{digest(csv_bytes(rows))}</code></p></html>')
    elif kind == "package":
        with zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("dataset.csv", csv_bytes(rows))
            archive.writestr("manifest.json", json.dumps({"input_sha256": digest(csv_bytes(rows)), "rows": len(rows)}))
    else:
        temp.write_text(json.dumps({"rows": len(rows), "total": sum(r["amount"] for r in rows)}))
    check = validate(temp, kind, rows)
    if not check["valid"]:
        raise ValueError(check["error"])
    if final.exists():
        raise ValueError("Canonical output already published")
    temp.replace(final)
    return {"worker_id": worker["id"], "attempt": worker["attempt"], "kind": kind, "filename": final.name, **check}
