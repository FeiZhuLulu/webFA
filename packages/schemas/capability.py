from pydantic import BaseModel

class Capability(BaseModel):
    id: str
    provider: str
    description: str = ""
