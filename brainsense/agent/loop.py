"""Minimal agentic loop over an OpenAI-compatible chat endpoint (Meta Model API / Llama).

Configure with env:
    BRAINSENSE_LLM_BASE_URL   e.g. the Meta Model API base URL (OpenAI-compatible)
    BRAINSENSE_LLM_API_KEY
    BRAINSENSE_LLM_MODEL
Falls back to a deterministic MockLLM when BRAINSENSE_LLM_MOCK=1 so the whole pipeline can be
smoke-tested without network or credits."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv

from .prompt import SYSTEM_PROMPT
from .tools import TOOLS, ToolRegistry

load_dotenv()  # .env in the project root (never committed)


@dataclass
class Turn:
    role: str
    content: str | None = None
    tool_calls: list[dict] | None = None
    tool_call_id: str | None = None
    name: str | None = None

    def to_msg(self) -> dict[str, Any]:
        m: dict[str, Any] = {"role": self.role}
        if self.content is not None:
            m["content"] = self.content
        if self.tool_calls:
            m["tool_calls"] = self.tool_calls
        if self.tool_call_id:
            m["tool_call_id"] = self.tool_call_id
        if self.name:
            m["name"] = self.name
        return m


class MockLLM:
    """Scripted stand-in: calls brain_eval once, then phrases the result. Keeps tests offline."""

    def __init__(self) -> None:
        self._step = 0

    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        last = messages[-1]
        if last["role"] == "user":
            item = last["content"].split("[item:")[1].split("]")[0] if "[item:" in last["content"] else "unknown"
            return {"content": None, "tool_calls": [{"id": "call_1", "type": "function",
                    "function": {"name": "brain_eval", "arguments": json.dumps({"item_id": item})}}]}
        res = json.loads(last["content"])
        heads = res.get("heads", {})
        parts = []
        for name, h in heads.items():
            if h is None:
                continue
            c = h.get("crowd", h)
            verdict = "좋아 보여" if c["score"] >= 0.6 else "별로야" if c["score"] <= 0.4 else "그저 그래"
            if c["confidence"] < 0.3:
                verdict = "잘 모르겠어"
            parts.append(f"{name}: {verdict} (상위 {100 - c['percentile']:.0f}%)")
        return {"content": " / ".join(parts) or "도구 결과가 비어 있어.", "tool_calls": None}


class OpenAICompatLLM:
    def __init__(self) -> None:
        from openai import OpenAI
        self.client = OpenAI(base_url=os.environ["BRAINSENSE_LLM_BASE_URL"],
                             api_key=os.environ["BRAINSENSE_LLM_API_KEY"])
        self.model = os.environ["BRAINSENSE_LLM_MODEL"]

    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        r = self.client.chat.completions.create(model=self.model, messages=messages, tools=tools,
                                                tool_choice="auto", temperature=0.4, max_tokens=1024)  # Muse counts reasoning tokens here
        m = r.choices[0].message
        return {"content": m.content,
                "tool_calls": [tc.model_dump() for tc in (m.tool_calls or [])] or None}


@dataclass
class Agent:
    registry: ToolRegistry
    llm: Any = None
    history: list[Turn] = field(default_factory=list)
    max_tool_rounds: int = 4

    def __post_init__(self) -> None:
        if self.llm is None:
            self.llm = MockLLM() if os.environ.get("BRAINSENSE_LLM_MOCK") == "1" else OpenAICompatLLM()
        self.history.append(Turn("system", SYSTEM_PROMPT))

    def ask(self, item_id: str, user_text: str) -> str:
        self.history.append(Turn("user", f"[item:{item_id}] {user_text}"))
        empty_retries = 0
        for _ in range(self.max_tool_rounds + 2):
            out = self.llm.chat([t.to_msg() for t in self.history], TOOLS)
            if not out["tool_calls"]:
                text = (out["content"] or "").strip()
                if not text and empty_retries < 2:
                    # Muse occasionally spends the budget on reasoning and returns no text; never store
                    # an empty assistant turn (the API rejects it on the next call) — nudge and retry.
                    empty_retries += 1
                    self.history.append(Turn("user", "(도구 결과를 바탕으로 2~3문장으로 바로 답해 줘)"))
                    continue
                if not text:
                    text = "잠깐 생각이 막혔어. 다시 한 번 물어봐 줘."
                self.history.append(Turn("assistant", text))
                return text
            self.history.append(Turn("assistant", out["content"], tool_calls=out["tool_calls"]))
            for tc in out["tool_calls"]:
                fn = tc["function"]
                args = json.loads(fn["arguments"] or "{}")
                result = self.registry.call(fn["name"], **args)
                self.history.append(Turn("tool", json.dumps(result, ensure_ascii=False),
                                         tool_call_id=tc["id"], name=fn["name"]))
        return "도구 호출이 너무 길어졌어. 다시 물어봐 줘."
