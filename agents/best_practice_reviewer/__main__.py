"""Run:  python -m agents.best_practice_reviewer   (A2A server on port 10002)"""

from agents.base.server import make_agent_card, serve
from agents.best_practice_reviewer.graph import REVIEWER, build_graph

PORT = 10002

card = make_agent_card(
    name=REVIEWER,
    description="Checks the changed Python code against best practices using an LLM. "
                "Returns a score out of 10 with a report.",
    port=PORT,
    skill_id="best_practice_review",
    skill_name="Best practice review",
    skill_description="Input: ReviewRequest JSON (data part). Output: ReviewerResult JSON artifact.",
    tags=["code-review", "python", "best-practices"],
    examples=["Check push 42 for Pythonic style and structure"],
)

if __name__ == "__main__":
    serve(card, build_graph(), REVIEWER, PORT)
