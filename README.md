# StreetRule

StreetRule answers one question: which rental-housing rules apply at this address, as of 1 Oct 2026? Every answer quotes a public source. It says unknown when the public record is missing a fact the rule depends on. It separates a bill from a law.

Not legal advice.

Live: https://streetrule.vercel.app

## What the judges get

| File | What it is |
|---|---|
| `output/rules.json` | 121 rules extracted from the supplied corpus. Each quote was checked against the source file. |
| `output/lookups.json` | A result for all 500 sample addresses, as of 2026-10-01. |
| `output/changes.json` | Change tests T1–T5: which addresses a legal change affects. |

The address page is `/`. The five change tests, each with a worked example, are at `/changes`.

## How a rule gets into the answer

1. `extract.py` sends each supplied document to the model and keeps a rule only when its quote appears in that document.
2. The model also records which property facts the rule depends on (year built, unit count, and so on). If the address file lacks one, the result is unknown.
3. `review/corrections.json` holds the human-checked fixes, each with a reason. Berkeley's algorithmic ban was adopted law, not a pending bill. California's screening-fee cap has two published dollar figures, so both cards are flagged.
4. `core/apply.py` matches an address to its legal city. Dorchester is Boston. San Ysidro is San Diego. A state rule yields to a city rule on rent increases and just-cause eviction.

## Limits, stated on purpose

- Hoboken, parts of Jersey City, Newark, and the struck Massachusetts rent-cap ballot question are links with no text in the corpus. Those addresses show the links under "Sources we could not read" instead of an invented rule.
- San Diego's algorithmic ordinance in the corpus is an unsigned draft, so it stays pending.
- The hour-16 Cambridge ordinance is not in the corpus yet. When it arrives, save the text and run `uv run python ingest_one.py incoming/t6.txt --jurisdiction "Cambridge, MA" --url URL`.

## Run

```bash
cp .env.example .env   # put OPENAI_API_KEY in .env
uv sync
uv run python extract.py
uv run python -c "from core.apply import write_outputs; write_outputs()"
uv run uvicorn app:app --reload
```

Open http://localhost:8000

The law text, the address list, and the rule format come from the RealPage starter pack supplied for this challenge.
