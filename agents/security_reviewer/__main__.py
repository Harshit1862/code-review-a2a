"""Run:  python -m agents.security_reviewer   (A2A server on port 10003)"""

from agents.base.server import make_agent_card, serve
from agents.security_reviewer.graph import REVIEWER, build_graph

PORT = 10003

card = make_agent_card(
    name=REVIEWER,
    description="Scans the changed Python code for security issues using an LLM. "
                "Returns a score out of 10 with a report.",
    port=PORT,
    skill_id="security_review",
    skill_name="Security review",
    skill_description="Input: ReviewRequest JSON (data part). Output: ReviewerResult JSON artifact.",
    tags=["code-review", "python", "security"],
    examples=["Scan push 42 for injection, secrets and unsafe deserialization"],
)

if __name__ == "__main__":
    serve(card, build_graph(), REVIEWER, PORT)
