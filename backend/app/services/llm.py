import json
import os
import re
from pathlib import Path

import requests
from fastapi.concurrency import run_in_threadpool


def _api_key() -> str:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if key:
        return key
    env_file = Path(os.getenv("OPENAI_ENV_FILE", "/run/secrets/totally.env"))
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("OPENAI_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


async def suggest_experiment(prompt: str) -> dict:
    key = _api_key()
    if not key:
        raise RuntimeError("OPENAI_API_KEY가 설정되지 않았습니다.")
    return await run_in_threadpool(_request_suggestion, key, prompt)


def _request_suggestion(api_key: str, prompt: str) -> dict:
    instruction = """당신은 실험 설계자입니다. 아래 상품/기능 설명을 바탕으로 버튼 문구 A/B 실험 초안을 만드세요. 반드시 JSON만 반환하세요.
스키마: {name, hypothesis, primary_metric, guardrail_metric, variants:[{variant_key,label,weight}], analysis_notes}
variant는 control과 treatment 두 개, weight 합계는 100으로 만드세요. 과장되거나 검증할 수 없는 지표는 쓰지 마세요."""
    response = requests.post(
        "https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": os.getenv("OPENAI_MODEL", "gpt-5.6-luna"),
            "instructions": instruction,
            "input": prompt,
            "text": {"verbosity": "low"},
            "store": False,
        },
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    text = data.get("output_text") or "".join(
        part.get("text", "")
        for item in data.get("output", [])
        for part in item.get("content", [])
        if part.get("type") == "output_text"
    )
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("LLM이 JSON 실험 초안을 반환하지 않았습니다.")
    return json.loads(match.group(0))
