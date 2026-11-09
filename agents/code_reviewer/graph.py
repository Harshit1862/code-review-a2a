"""Code reviewer: correctness, logic, error handling, readability.

Graph: llm_review -> finalize
"""

from langgraph.graph import END, START, StateGraph

from agents.base.graph_parts import ReviewState, make_finalize_node, make_llm_node

REVIEWER = "Code Reviewer"

SYSTEM_PROMPT = """You are a senior Python engineer doing a code review focused on CODE QUALITY:
- correctness and logic bugs, wrong conditions, off-by-one errors, unhandled edge cases (None, empty input)
- error handling (bare except, swallowed exceptions, missing cleanup)
- readability: unclear names, functions doing too much, deep nesting, duplication
- a file that does not parse as valid Python is a critical finding
Do NOT comment on security (another agent does that) or on pure formatting/style lint (another agent does that)."""


def build_graph():
    g = StateGraph(ReviewState)
    g.add_node("llm_review", make_llm_node(SYSTEM_PROMPT))
    g.add_node("finalize", make_finalize_node(REVIEWER))
    g.add_edge(START, "llm_review")
    g.add_edge("llm_review", "finalize")
    g.add_edge("finalize", END)
    return g.compile()
