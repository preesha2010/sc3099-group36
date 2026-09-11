from typing import List

from pydantic import BaseModel, EmailStr


class EnrollmentCreate(BaseModel):
    student_id: str
    course_id: str


class BulkEnrollmentCreate(BaseModel):
    course_id: str
    student_emails: List[EmailStr]
    create_accounts: bool = False
