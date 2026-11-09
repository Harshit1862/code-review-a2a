"""Offline stand-in for the LLM (LLM_PROVIDER=fake).

It lets you test the whole pipeline (ingest -> DB -> chat -> A2A -> scores) with no API key.
Its "reasoning" is a few keyword rules, so replies are basic. Use Groq for real reviews.
"""

import json
import re
import uuid
from typing import List

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


class FakeChatModel:
    def bind_tools(self, tools, **kwargs):
        return _FakeToolCaller()

    def with_structured_output(self, schema, **kwargs):
        return _FakeStructured(schema)


# ------------------------------------------------------------ reviewer side


_RULES = {
    "code": [
        (r"except\s*:", "high", "Bare except hides errors",
         "Catching everything also swallows KeyboardInterrupt and real bugs.", "Catch specific exceptions."),
        (r"range\(len\(", "low", "Index loop instead of enumerate",
         "Looping over range(len(x)) is harder to read.", "Use enumerate()."),
    ],
    "best": [
        (r"\bprint\(", "low", "print used instead of logging",
         "print output cannot be filtered or routed.", "Use the logging module."),
    ],
    "security": [
        (r"verify\s*=\s*False", "high", "TLS verification disabled",
         "Requests can be intercepted.", "Remove verify=False."),
        (r"(API_KEY|SECRET|TOKEN|PASSWORD)\s*=\s*['\"]", "high", "Hardcoded secret",
         "Secrets in code end up in git history.", "Load secrets from environment variables."),
    ],
}


class _FakeStructured:
    def __init__(self, schema):
        self.schema = schema

    async def ainvoke(self, messages):
        system, user = messages[0].content, messages[-1].content
        kind = "security" if "security reviewer" in system else "best" if "best-practices" in system else "code"
        findings, current_file = [], None
        for line in user.splitlines():
            if line.startswith("### File: "):
                current_file = line[len("### File: "):].split(" (")[0]
                continue
            match = re.match(r"^>>\s+(\d+) \| (.*)$", line)
            if not match or not current_file:
                continue
            lineno, code = int(match.group(1)), match.group(2)
            for pattern, sev, title, detail, fix in _RULES[kind]:
                if re.search(pattern, code):
                    findings.append({"file": current_file, "line": lineno, "severity": sev,
                                     "title": title, "detail": detail, "suggestion": fix})
        summary = f"(offline fake LLM) Found {len(findings)} extra issue(s) in the changed lines."
        weight = {"critical": 4, "high": 2, "medium": 1, "low": 0.5, "info": 0}
        score = max(0.0, 10.0 - sum(weight[f["severity"]] for f in findings))
        return self.schema(summary=summary, findings=findings[:8], score=round(score, 1))


# ------------------------------------------------------------ orchestrator side


def _period(text: str):
    for key, period in (("yesterday", "yesterday"), ("today", "today"), ("this week", "this_week"),
                        ("last 7 days", "last_7_days"), ("this month", "this_month")):
        if key in text:
            return period
    return None


def _project(text: str):
    match = re.search(r"\b(?:on|for|in|of)\s+(?:project\s+)?([a-z0-9_.\-]+)", text)
    if match and match.group(1) not in {"today", "yesterday", "the", "this", "push", "it", "last", "my"}:
        return match.group(1)
    return None


def _latest_push_id(messages: List) -> int:
    for m in reversed(messages):
        if isinstance(m, ToolMessage):
            found = re.search(r'"push_id":\s*(\d+)', str(m.content))
            if found:
                return int(found.group(1))
    return 0


class _FakeToolCaller:
    async def ainvoke(self, messages):
        last = messages[-1]
        if isinstance(last, ToolMessage):
            return AIMessage(content=self._summarize(messages))
        text = str(last.content).lower()
        name, args = self._route(text, messages)
        if name is None:
            return AIMessage(content="(offline fake LLM) Ask me about projects, pushes, counts or reviews.")
        return AIMessage(content="", tool_calls=[{"name": name, "args": args,
                                                  "id": f"call_{uuid.uuid4().hex[:8]}", "type": "tool_call"}])

    def _route(self, text: str, messages: List):
        id_match = re.search(r"(?:#|push\s*#?)(\d+)", text)
        push_id = int(id_match.group(1)) if id_match else None
        if any(w in text for w in ("score", "review", "rate")):
            if "what was" in text or "saved" in text:
                return "get_review", {"push_id": push_id or _latest_push_id(messages)}
            pid = push_id or _latest_push_id(messages)
            if not pid:
                return "search_pushes", {"limit": 1}
            return "review_push", {"push_id": pid, "force": "again" in text or "re-run" in text}
        if "how many" in text or "count" in text:
            args = {"period": _period(text), "project": _project(text)}
            return "count_pushes", {k: v for k, v in args.items() if v}
        if "project" in text and any(w in text for w in ("list", "which", "what", "all")):
            return "list_projects", {}
        if push_id and any(w in text for w in ("changed", "detail", "show")):
            return "get_push_details", {"push_id": push_id}
        args = {"period": _period(text), "project": _project(text), "limit": 5}
        return "search_pushes", {k: v for k, v in args.items() if v}

    def _summarize(self, messages: List) -> str:
        last_human = max(i for i, m in enumerate(messages) if isinstance(m, HumanMessage))
        parts = []
        for m in messages[last_human:]:
            if not isinstance(m, ToolMessage):
                continue
            try:
                data = json.loads(m.content)
            except (json.JSONDecodeError, TypeError):
                parts.append(str(m.content)[:500])
                continue
            if isinstance(data, dict) and "scores" in data and isinstance(data["scores"], dict) \
                    and any(isinstance(v, dict) for v in data["scores"].values()):
                lines = [f"Push #{data.get('push_id')} review" + (" (saved)" if data.get("cached") else "") + ":"]
                for label, s in data["scores"].items():
                    lines.append(f"- {label}: {s.get('score')} - {s.get('summary') or s.get('error')}")
                    lines += [f"    {f}" for f in s.get("top_findings", [])[:3]]
                parts.append("\n".join(lines))
            elif isinstance(data, dict) and "pushes" in data:
                if not data["pushes"]:
                    parts.append("No matching pushes.")
                else:
                    rows = [f"#{p['push_id']} {p['project']}/{p['branch']} at {p['pushed_at']} "
                            f"({p['commits']} commit(s), {p['files_changed']} file(s), {p['review_status']})"
                            for p in data["pushes"]]
                    parts.append(f"Found {data['total_matching']} push(es):\n" + "\n".join(rows))
            elif isinstance(data, dict) and "count" in data:
                parts.append(f"{data['count']} push(es) match.")
            else:
                parts.append(json.dumps(data, default=str)[:800])
        return "(offline fake LLM)\n" + "\n\n".join(parts)
