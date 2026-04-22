from pydantic import BaseModel


class StaffMemberOut(BaseModel):
    id: str
    display_name: str | None
    email: str
    role: str

    model_config = {"from_attributes": True}


class StaffListResponse(BaseModel):
    items: list[StaffMemberOut]
