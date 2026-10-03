import csv
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

from core.apply import DEFAULT_AS_OF, change_demos, load_rules, lookup  # noqa: E402
from core.llm import available  # noqa: E402

app = FastAPI(title="StreetRule")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


def addresses() -> list[dict]:
    with (ROOT / "data" / "sample_addresses.csv").open() as f:
        return list(csv.DictReader(f))


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/changes")
def changes_page():
    return FileResponse(ROOT / "static" / "changes.html")


@app.get("/api/changes")
def changes():
    return change_demos()


@app.get("/api/health")
def health():
    rules = load_rules()
    return {"ok": True, "llm": available(), "rules": len(rules), "as_of": DEFAULT_AS_OF}


@app.get("/api/addresses")
def list_addresses(q: str = ""):
    needle = q.strip().lower()
    rows = []
    for row in addresses():
        label = f"{row['street_address']}, {row['postal_city']}, {row['state']}"
        if needle and needle not in label.lower() and needle not in row["address_id"].lower():
            continue
        rows.append({"address_id": row["address_id"], "label": label})
        if len(rows) == 20:
            break
    return rows


@app.get("/api/lookup")
def get_lookup(address_id: str, as_of: str = DEFAULT_AS_OF):
    row = next((r for r in addresses() if r["address_id"] == address_id), None)
    if row is None:
        raise HTTPException(404, "Address not in the sample")
    return lookup(load_rules(), row, as_of)
