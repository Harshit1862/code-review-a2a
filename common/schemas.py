"""Data contracts shared by the ingest service, the orchestrator and the reviewer agents."""

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

Severity = Literal["critical", "high", "medium", "low", "info"]


class FileChange(BaseModel):
    """One changed file inside a push."""

    path: str
    status: str  # added | modified | removed | renamed
    additions: int = 0
    deletions: int = 0
    patch: Optional[str] = None  # unified diff for this file
    content: Optional[str] = None  # full file content at the pushed commit
    changed_lines: List[int] = Field(default_factory=list)  # added/modified line numbers


class ReviewRequest(BaseModel):
    """What the orchestrator sends to every reviewer agent (as an A2A data part)."""

    push_id: int
    project: str
    branch: Optional[str] = None
    commit_messages: List[str] = Field(default_factory=list)
    files: List[FileChange]
    extra_instructions: Optional[str] = None  # contents of the repo's prompt.md, if any


class Finding(BaseModel):
    file: str
    line: Optional[int] = None
    severity: Severity
    title: str
    detail: str = ""
    suggestion: str = ""
    source: str = "llm"
    rule: Optional[str] = None


class LLMFinding(BaseModel):
    """A single issue the LLM reports. Field descriptions guide the model."""

    file: str = Field(description="Path of the file, exactly as given in the input")
    line: Optional[int] = Field(
        default=None, description="Line number in the new version of the file, if known"
    )
    severity: Severity = Field(
        description=(
            "critical = exploitable or data-loss bug; high = likely bug or serious risk; "
            "medium = should fix soon; low = minor improvement; info = note only"
        )
    )
    title: str = Field(description="Short title, max 10 words")
    detail: str = Field(description="What is wrong and why it matters, 1-3 sentences")
    suggestion: str = Field(description="Concrete fix, 1-2 sentences")


class LLMReview(BaseModel):
    """Structured output the reviewer LLM must return."""

    score: float = Field(
        ge=0, le=10,
        description=(
            "Your own score out of 10 for this review dimension only. 10 = no issues. "
            "A critical issue should bring this to roughly 0-4; high issues should cost more "
            "than medium/low ones; no findings means 10."
        ),
    )
    summary: str = Field(description="2-4 sentence overall assessment of the change")
    findings: List[LLMFinding] = Field(
        default_factory=list, description="Issues found, most important first, max 8"
    )


class ReviewerResult(BaseModel):
    """What each reviewer agent returns (as an A2A artifact)."""

    reviewer: str
    score: float
    summary: str
    report: str
    findings: List[Finding]
    severity_counts: Dict[str, int]
    score_breakdown: str
    files_reviewed: int
    changed_lines: int
    tool: Optional[str] = None
