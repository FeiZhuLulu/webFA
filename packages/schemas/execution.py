from pydantic import BaseModel

class Execution(BaseModel):
    id: str
    plan_id: str
    status: str = "queued"
