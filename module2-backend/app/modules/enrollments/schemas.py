from datetime import datetime
from typing import List

from pydantic import BaseModel, EmailStr


class EnrollmentCreate(BaseModel):
    student_id: str
    course_id: str


class EnrollmentResponse(BaseModel):
    id: str
    student_id: str
    course_id: str
    is_active: bool
    enrolled_at: datetime

    model_config = {"from_attributes": True}


class BulkEnrollmentCreate(BaseModel):
    course_id: str
    student_emails: List[EmailStr]
    create_accounts: bool = False