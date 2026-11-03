"""Brain home: the Hermes-style workspace that makes the agent inspectable and self-improving.

Ported from Hermes Agent's conventions (NousResearch/hermes-agent, MIT) and adapted to a brain-state
memory:
  SOUL.md      identity, user-authored, loaded verbatim at the top of every system prompt
  MEMORY.md    §-delimited declarative facts that apply to EVERY session (hard char budget)
  USER.md      §-delimited facts about the user + a "## taste" section the sleep pass regenerates
  skills/      agentskills.io SKILL.md files (YAML frontmatter + procedure); only the index (name +
               description) rides in the prompt, the body is loaded on demand with skill_view
  engrams.sqlite / rules/   the brain-state memory (engram.py) and its Markdown mirror (sleep.py)

Invariant borrowed from Hermes: the prompt prefix must be stable within a conversation (caching), so
`prompt()` is deterministic for a given set of files and the server caches it for a minute.
"""
from __future__ import annotations

import os
import re
import shutil
import time
from pathlib import Path
from typing import Any

ENTRY_DELIMITER = "§ "
MEMORY_CHAR_LIMIT = 2200      # Hermes defaults
USER_CHAR_LIMIT = 1375
SEED_DIR = Path(__file__).resolve().parent.parent / "home_seed"

MEMORY_GUIDANCE = (
    "You have persistent memory, carried across sessions and loaded into each new session's context. "
    "Skills come first: when you learn something while doing a task — a procedure, a pitfall, the user's "
    "preferences and corrections for that kind of work — record it in the skill you used or built for the "
    "task (skill_manage), where it loads only when relevant. Memory (brain_memory target='memory') is the "
    "narrow exception for facts that apply to EVERY session regardless of task; target='user' is for durable "
    "facts about the user. Both have a hard character budget: when they fill, replace or consolidate stale "
    "entries rather than skipping the save. Write entries as declarative facts, not instructions to yourself "
    "('User prefers concise replies' ✓, 'Always reply concisely' ✗). A fact stale within a week belongs in "
    "the conversation, not in memory. Your taste model of the user is NOT in memory: it is the personal head "
    "and the rules the sleep pass mines from brain states (brain_rules); do not duplicate them as text."
)


class Home:
    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root or os.environ.get("BRAINSENSE_HOME", "state/brain_home"))
        self.root.mkdir(parents=True, exist_ok=True)
        self._seed()
        self._prompt_cache: tuple[float, dict[str, Any]] | None = None

    # ---- files ---------------------------------------------------------------------------------
    def _seed(self) -> None:
        """First run: copy the seed workspace (never overwrite user edits)."""
        if not SEED_DIR.exists():
            return
        for src in SEED_DIR.rglob("*"):
            if src.is_dir():
                continue
            dst = self.root / src.relative_to(SEED_DIR)
            if not dst.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dst)

    def _read(self, name: str) -> str:
        p = self.root / name
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def soul(self) -> str:
        return self._read("SOUL.md").strip()

    # ---- memory store (MEMORY.md / USER.md) ---------------------------------------------------
    def _target(self, target: str) -> tuple[Path, int]:
        if target == "memory":
            return self.root / "MEMORY.md", MEMORY_CHAR_LIMIT
        if target == "user":
            return self.root / "USER.md", USER_CHAR_LIMIT
        raise ValueError("target must be 'memory' or 'user'")

    def entries(self, target: str) -> list[str]:
        path, _ = self._target(target)
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        # the taste section of USER.md is machine-owned; entries are only the § lines above it
        text = text.split("\n## taste", 1)[0]
        return [e.strip() for e in text.split(ENTRY_DELIMITER) if e.strip()]

    def _write_entries(self, target: str, entries: list[str]) -> None:
        path, _ = self._target(target)
        tail = ""
        if path.exists() and "\n## taste" in path.read_text(encoding="utf-8"):
            tail = "\n## taste" + path.read_text(encoding="utf-8").split("\n## taste", 1)[1]
        body = "".join(f"{ENTRY_DELIMITER}{e.strip()}\n" for e in entries)
        path.write_text(body + tail, encoding="utf-8")
        self._prompt_cache = None

    def memory(self, action: str, target: str = "memory", content: str | None = None,
               old_text: str | None = None) -> dict[str, Any]:
        """add | replace | remove, with Hermes' write gate: char budget and declarative phrasing."""
        path, limit = self._target(target)
        entries = self.entries(target)
        if action == "add":
            if not content or not content.strip():
                return {"error": "content required"}
            c = content.strip()
            if re.match(r"^(always|never|do not|don't|remember to|make sure)\b", c, re.I):
                return {"error": "write entries as declarative facts, not instructions to yourself"}
            new_total = sum(len(e) + 2 for e in entries) + len(c) + 2
            if new_total > limit:
                return {"error": f"would put {target} at {new_total}/{limit} chars; replace or remove a stale entry first",
                        "entries": entries}
            entries.append(c)
        elif action == "replace":
            if not old_text or content is None:
                return {"error": "old_text and content required"}
            idx = next((i for i, e in enumerate(entries) if old_text.strip() in e), None)
            if idx is None:
                return {"error": "old_text not found", "entries": entries}
            entries[idx] = content.strip()
            if sum(len(e) + 2 for e in entries) > limit:
                return {"error": f"over the {limit}-char budget", "entries": entries}
        elif action == "remove":
            if not old_text:
                return {"error": "old_text required"}
            before = len(entries)
            entries = [e for e in entries if old_text.strip() not in e]
            if len(entries) == before:
                return {"error": "old_text not found", "entries": entries}
        else:
            return {"error": "action must be add | replace | remove"}
        self._write_entries(target, entries)
        return {"ok": True, "target": target, "chars": sum(len(e) + 2 for e in entries), "limit": limit, "entries": entries}

    def set_taste_section(self, rules: list[dict[str, Any]], report_line: str) -> None:
        """Sleep writes the machine-owned taste section of USER.md (the Markdown mirror of `rules`)."""
        path, _ = self._target("user")
        entries = self.entries("user")
        body = "".join(f"{ENTRY_DELIMITER}{e}\n" for e in entries)
        taste = "\n## taste\n" + (report_line + "\n" if report_line else "") + "".join(
            f"- {r['text']} (confidence {r['confidence']})\n" for r in rules)
        path.write_text(body + taste, encoding="utf-8")
        self._prompt_cache = None

    # ---- skills --------------------------------------------------------------------------------
    @staticmethod
    def _frontmatter(text: str) -> tuple[dict[str, str], str]:
        m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
        if not m:
            return {}, text
        meta: dict[str, str] = {}
        for line in m.group(1).splitlines():
            if ":" in line and not line.startswith(" "):
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip().strip('"')
        return meta, m.group(2)

    def skills_index(self) -> list[dict[str, str]]:
        out = []
        for f in sorted((self.root / "skills").rglob("SKILL.md")):
            meta, _ = self._frontmatter(f.read_text(encoding="utf-8")[:4000])
            if meta.get("archived") == "true":
                continue
            out.append({"name": meta.get("name", f.parent.name), "description": meta.get("description", ""),
                        "category": f.parent.parent.name, "path": str(f.relative_to(self.root))})
        return out

    def skill_view(self, name: str) -> dict[str, Any]:
        for f in (self.root / "skills").rglob("SKILL.md"):
            meta, body = self._frontmatter(f.read_text(encoding="utf-8"))
            if meta.get("name", f.parent.name) == name:
                self._touch_usage(name)
                return {"name": name, "frontmatter": meta, "body": body.strip(), "path": str(f.relative_to(self.root))}
        return {"error": f"no skill named {name}", "available": [s["name"] for s in self.skills_index()]}

    def skill_manage(self, action: str, name: str, content: str | None = None, category: str = "learned",
                     old_text: str | None = None) -> dict[str, Any]:
        """create | patch | archive. Hermes invariants: never delete (archive is recoverable), a skill is a
        SKILL.md with frontmatter + a procedure that ends in 'Done when'."""
        if not re.match(r"^[a-z0-9][a-z0-9-]{1,60}$", name):
            return {"error": "name must be kebab-case"}
        d = self.root / "skills" / re.sub(r"[^a-z0-9-]", "-", category.lower()) / name
        f = d / "SKILL.md"
        if action == "create":
            if f.exists():
                return {"error": "exists; use patch"}
            if not content or "## Done when" not in content and "## done when" not in content.lower():
                return {"error": "a skill needs a procedure that ends with a '## Done when' section"}
            body = content if content.lstrip().startswith("---") else (
                f"---\nname: {name}\ndescription: \"{content.strip().splitlines()[0][:120].lstrip('# ')}\"\nversion: 0.1.0\n"
                f"author: BrainSense (learned)\nlicense: MIT\nmetadata:\n  brainsense:\n    learned_at: {time.strftime('%Y-%m-%d')}\n---\n\n{content}")
            d.mkdir(parents=True, exist_ok=True)
            f.write_text(body, encoding="utf-8")
        elif action == "patch":
            target = self._find_skill(name)
            if target is None:
                return {"error": f"no skill named {name}"}
            text = target.read_text(encoding="utf-8")
            if old_text and old_text in text and content is not None:
                text = text.replace(old_text, content, 1)
            elif content:
                text = text.rstrip() + "\n\n" + content.strip() + "\n"
            else:
                return {"error": "content required"}
            target.write_text(text, encoding="utf-8")
            f = target
        elif action == "archive":
            target = self._find_skill(name)
            if target is None:
                return {"error": f"no skill named {name}"}
            text = target.read_text(encoding="utf-8")
            if "archived: true" not in text:
                text = text.replace("\n---\n", "\narchived: true\n---\n", 1)
            target.write_text(text, encoding="utf-8")
            f = target
        else:
            return {"error": "action must be create | patch | archive"}
        self._prompt_cache = None
        return {"ok": True, "name": name, "path": str(f.relative_to(self.root))}

    def _find_skill(self, name: str) -> Path | None:
        for f in (self.root / "skills").rglob("SKILL.md"):
            meta, _ = self._frontmatter(f.read_text(encoding="utf-8")[:4000])
            if meta.get("name", f.parent.name) == name:
                return f
        return None

    def _touch_usage(self, name: str) -> None:
        p = self.root / ".skill_usage.json"
        import json
        d = json.loads(p.read_text()) if p.exists() else {}
        d.setdefault(name, {"views": 0}); d[name]["views"] += 1; d[name]["last"] = time.time()
        p.write_text(json.dumps(d))

    # ---- prompt --------------------------------------------------------------------------------
    def prompt(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        """Everything the voice needs at the top of its system prompt, assembled deterministically."""
        if self._prompt_cache and time.time() - self._prompt_cache[0] < 60:
            return self._prompt_cache[1]
        skills = self.skills_index()
        user_path = self.root / "USER.md"
        user_text = user_path.read_text(encoding="utf-8") if user_path.exists() else ""
        taste = user_text.split("\n## taste", 1)[1].strip() if "\n## taste" in user_text else ""
        block = {
            "soul": self.soul(),
            "memory_guidance": MEMORY_GUIDANCE,
            "memory": self.entries("memory"),
            "user": self.entries("user"),
            "taste": taste,
            "skills": [{"name": s["name"], "description": s["description"]} for s in skills],
            "skills_guidance": ("Skills are procedures you can load with skill_view(name) when a task matches a "
                                "description below; load one before doing that kind of work, and improve it with "
                                "skill_manage(patch) when you learn something."),
        }
        if extra:
            block.update(extra)
        text = "\n".join([
            block["soul"], "",
            "## Memory", block["memory_guidance"], *[f"- {e}" for e in block["memory"]], "",
            "## User", *[f"- {e}" for e in block["user"]], *( ["", "### Taste (mined from brain states)", taste] if taste else []), "",
            "## Skills", block["skills_guidance"], *[f"- {s['name']}: {s['description']}" for s in block["skills"]],
        ])
        block["text"] = text
        self._prompt_cache = (time.time(), block)
        return block
