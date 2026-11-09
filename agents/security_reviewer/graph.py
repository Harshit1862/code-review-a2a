"""Security reviewer: LLM review for vulnerabilities.

Graph: llm_review -> finalize
"""

from langgraph.graph import END, START, StateGraph

from agents.base.graph_parts import ReviewState, make_finalize_node, make_llm_node

REVIEWER = "Security Reviewer"

SYSTEM_PROMPT = """You are an application security reviewer for Python code. Look for:
- injection: SQL, shell/OS command, template, eval/exec
- hardcoded secrets, tokens, passwords; secrets written to logs
- unsafe deserialization (pickle, yaml.load), path traversal, SSRF, insecure temp files
- weak crypto or randomness for security purposes, disabled TLS verification
- missing authentication/authorization checks, sensitive data exposure
If something looks like a false positive, say so in the summary instead of flagging it.
Do NOT report style or general code-quality issues."""


def build_graph():
    g = StateGraph(ReviewState)
    g.add_node("llm_review", make_llm_node(SYSTEM_PROMPT))
    g.add_node("finalize", make_finalize_node(REVIEWER))
    g.add_edge(START, "llm_review")
    g.add_edge("llm_review", "finalize")
    g.add_edge("finalize", END)
    return g.compile()
