"""Best-practice reviewer: LLM review of Pythonic style and structure.

Graph: llm_review -> finalize
"""

from langgraph.graph import END, START, StateGraph

from agents.base.graph_parts import ReviewState, make_finalize_node, make_llm_node

REVIEWER = "Best Practice Reviewer"

SYSTEM_PROMPT = """You are a Python best-practices reviewer. Focus on:
- idiomatic, modern Python (comprehensions, context managers, f-strings, pathlib, dataclasses)
- type hints and docstrings on public functions
- logging instead of print, no magic numbers, constants and configuration handled properly
- structure: single responsibility, sensible module/function boundaries, no global mutable state
- obvious lint issues (unused imports/variables, overly complex functions, non-idiomatic loops)
Do NOT report security issues or logic bugs (other agents do that)."""


def build_graph():
    g = StateGraph(ReviewState)
    g.add_node("llm_review", make_llm_node(SYSTEM_PROMPT))
    g.add_node("finalize", make_finalize_node(REVIEWER))
    g.add_edge(START, "llm_review")
    g.add_edge("llm_review", "finalize")
    g.add_edge("finalize", END)
    return g.compile()
