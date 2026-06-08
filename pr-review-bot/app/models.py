"""
Pydantic data models for the PR Review Bot.

These schemas serve two purposes:
1. Validating structured JSON output from the LLM
2. Defining the data contract between the review engine and GitHub client
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CommentThread(BaseModel):
    """A single inline review comment attached to a specific line in a file."""

    file: str = Field(description="Relative file path, e.g. 'src/auth/login.py'")
    line: int = Field(description="Line number in the NEW version of the file (right side of diff)")
    severity: Literal["critical", "suggestion", "nit"] = Field(
        description="How important this comment is"
    )
    category: Literal["security", "logic", "style", "performance"] = Field(
        description="What kind of issue this is"
    )
    body: str = Field(description="The review comment text")


class ReviewResult(BaseModel):
    """The complete review output from the LLM for a single PR."""

    verdict: Literal["looks-good", "needs-work"] = Field(
        description="Overall assessment of the PR"
    )
    summary: str = Field(description="A brief top-level summary of the review")
    comments: list[CommentThread] = Field(
        default_factory=list, description="Inline comments on specific lines"
    )
