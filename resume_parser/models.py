from pydantic import BaseModel
from typing import Optional


class ContactInfo(BaseModel):
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    linkedin: Optional[str] = None


class WorkExperience(BaseModel):
    company: str
    role: str
    duration: Optional[str] = None
    description: Optional[str] = None


class Education(BaseModel):
    institution: str
    degree: str
    year: Optional[str] = None


class ParsedResume(BaseModel):
    name: Optional[str] = None
    contact: ContactInfo = ContactInfo()
    skills: list[str] = []
    work_experience: list[WorkExperience] = []
    education: list[Education] = []
    certifications: list[str] = []
    raw_text: Optional[str] = None


class ParseResponse(BaseModel):
    success: bool
    filename: str
    data: Optional[ParsedResume] = None
    error: Optional[str] = None
    parse_time_seconds: Optional[float] = None
