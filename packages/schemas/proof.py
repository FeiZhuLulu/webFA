from pydantic import BaseModel

class Proof(BaseModel):
    id: str
    provider: str
    proof_type: str
