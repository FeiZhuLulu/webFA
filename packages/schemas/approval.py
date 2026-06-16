from pydantic import BaseModel

class Approval(BaseModel):
    id: str
    plan_id: str
    status: str = "pending"
