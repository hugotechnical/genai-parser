from typing import Optional
from pydantic import BaseModel, Field
import uuid


class FileResponse(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique file ID")
    file_name: str
    file_size: int
    file_type: str
    extracted_content: str

    class Config:
        json_schema_extra = {
            "example": {
                "id": "7e5f32f8-47a0-4b6b-b321-9c6e379b64d1",
                "file_name": "report.pdf",
                "file_size": 1048576,
                "file_type": "application/pdf",
                "extracted_content": "# Report 2024\n\n## Revenue\n- Increased by 20%.",
            }
        }


class ParsedResult(BaseModel):
    is_success: bool
    content: Optional[str]
    failed_reason: Optional[str] = "No reason"