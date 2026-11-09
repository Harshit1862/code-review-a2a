"""Reusable LangGraph pieces: the state shape and the LLM + finalize nodes."""

from typing import List, TypedDict

from agents.base.review_utils import finalize, llm_review
from common.schemas import Finding, ReviewRequest


class ReviewState(TypedDict, total=False):
    request: dict  # ReviewRequest as a dict
    llm_findings: List[dict]  # from the LLM
    summary: str
    score: float  # the LLM's own score for this review dimension
    result: dict  # ReviewerResult as a dict


def make_llm_node(system_prompt: str):
    async def llm_node(state: ReviewState) -> dict:
        request = ReviewRequest.model_validate(state["request"])
        if not any(f.content for f in request.files):
            return {"llm_findings": [], "summary": "No reviewable files in this push.", "score": 10.0}
        review = await llm_review(system_prompt, request)
        findings = [Finding(**f.model_dump(), source="llm").model_dump() for f in review.findings[:8]]
        return {"llm_findings": findings, "summary": review.summary, "score": review.score}

    return llm_node


def make_finalize_node(reviewer: str):
    async def finalize_node(state: ReviewState) -> dict:
        request = ReviewRequest.model_validate(state["request"])
        result = finalize(
            reviewer=reviewer,
            request=request,
            llm_findings=[Finding.model_validate(f) for f in state.get("llm_findings", [])],
            summary=state.get("summary", ""),
            score=state.get("score", 10.0),
        )
        return {"result": result}

    return finalize_node
