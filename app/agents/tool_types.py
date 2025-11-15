"""Shared data structures for tool coordination."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class ToolErrorPayload(BaseModel):
    error_code: str = Field(..., description="Stable identifier for the failure")
    message: str = Field(..., description="Short diagnostic hint")


class SubAgentToolResult(BaseModel):
    status: Literal["SUCCESS", "BUSINESS_ERROR", "TOOL_FAILURE"] = Field(
        ...,
        description="SUCCESS for completed tasks, BUSINESS_ERROR for business-level issues, TOOL_FAILURE for ToolAgent faults",
    )
    payload: dict[str, Any] | None = Field(
        default=None,
        description="Machine-readable payload returned by the tool when status is SUCCESS",
    )
    error: ToolErrorPayload | None = Field(
        default=None,
        description="Structured error information returned when status is not SUCCESS",
    )

    @model_validator(mode="after")
    def _validate_payload_error(self) -> "SubAgentToolResult":
        if self.payload and self.error:
            raise ValueError("payload and error cannot be used at the same time")
        if self.payload is None and self.error is None:
            raise ValueError("either payload or error must be provided")
        return self


__all__ = ["ToolErrorPayload", "SubAgentToolResult"]
