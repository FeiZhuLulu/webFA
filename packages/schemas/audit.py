from pydantic import BaseModel

class AuditEvent(BaseModel):
    id: str
    event_type: str
    event_payload: dict = {}
