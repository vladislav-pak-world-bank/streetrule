# StreetRule

For a renter, a small owner, or an advocate, given an apartment address in the RealPage sample, StreetRule returns the housing rules that apply on 1 Oct 2026, with a quotation from the public source. It says unknown when the public record is missing a fact the rule depends on.

Not legal advice.

## Run

```bash
cp .env.example .env   # put OPENAI_API_KEY in .env
uv sync
uv run python extract.py
uv run python -c "from core.apply import write_outputs; write_outputs()"
uv run uvicorn app:app --reload
```

Open http://localhost:8000

`extract.py` reads `corpus/text/` and writes `output/rules.json`. The lookup page and `output/lookups.json` are built from those rules plus `data/sample_addresses.csv`. `output/changes.json` answers change tests T1–T5.

The law text, the address list, and the rule format come from the RealPage starter pack supplied for this challenge.
