from pydantic import BaseModel, Field

class GoldenCase(BaseModel):
    id: str
    input: str
    context_tags: list[str] = []
    expected_tools: list[str] = []
    expected_citations_contains: list[str] = []
    forbidden_behaviors: list[str] = []
    reference_answer: str | None = None
    severity: str = "P1"

class CaseScore(BaseModel):
    id: str
    pass_: bool = Field(alias="pass")
    tool_match: float
    citation_ok: bool
    faithfulness: float | None = None  # 1-5
    notes: str = ""
    failure_mode: str | None = None

# LLM judge prompt
JUDGE = """You grade faithfulness of ASSISTANT to EVIDENCE (tool results).
Score 1-5. 5=fully grounded; 1=hallucinated. List unsupported claims.
Return JSON: {"score": n, "unsupported": [], "rationale": "..."}
"""
