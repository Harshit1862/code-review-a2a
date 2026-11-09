"""Run:  python -m agents.code_reviewer   (A2A server on port 10001)"""

from agents.base.server import make_agent_card, serve
from agents.code_reviewer.graph import REVIEWER, build_graph

PORT = 10001

card = make_agent_card(
    name=REVIEWER,
    description="Reviews the changed Python code for correctness, error handling and readability. "
                "Returns a score out of 10 with a report.",
    port=PORT,
    skill_id="code_quality_review",
    skill_name="Code quality review",
    skill_description="Input: ReviewRequest JSON (data part). Output: ReviewerResult JSON artifact.",
    tags=["code-review", "python", "quality"],
    examples=["Review push 42 for logic bugs and readability"],
)

if __name__ == "__main__":
    serve(card, build_graph(), REVIEWER, PORT)
