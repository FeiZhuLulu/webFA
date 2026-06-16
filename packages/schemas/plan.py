from pydantic import BaseModel, Field

class Plan(BaseModel):
    id: str
    transaction_id: str
    steps: list[dict] = Field(default_factory=list)
    status: str = "draft"
