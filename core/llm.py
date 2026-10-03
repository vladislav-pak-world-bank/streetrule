import json
import os

from openai import OpenAI


def available() -> bool:
    return bool(os.getenv("OPENAI_API_KEY"))


def structured(system: str, user: str, schema: dict) -> dict:
    model = os.getenv("OPENAI_MODEL") or "gpt-6-luna"
    client = OpenAI(timeout=120)
    resp = client.responses.create(
        model=model,
        instructions=system,
        input=user,
        text={"format": {"type": "json_schema", "name": "result", "schema": schema, "strict": True}},
    )
    return json.loads(resp.output_text)
