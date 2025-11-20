"""
Database Schemas

CureSight data models
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime

class Query(BaseModel):
    patient_language: str = Field(..., description="BCP-47 code like en-US, hi-IN")
    input_type: str = Field(..., description="text | audio | image")
    symptom_text: Optional[str] = Field(None, description="User provided symptoms text")
    ocr_text: Optional[str] = Field(None, description="Extracted text from prescription image")
    combined_text: Optional[str] = Field(None, description="Combined text used for analysis")
    analysis: Dict[str, Any] = Field(default_factory=dict)

class DoctorNote(BaseModel):
    query_id: str = Field(..., description="Associated query document id as string")
    note: str = Field(..., description="Doctor note")
    author: Optional[str] = Field(None, description="Doctor name or identifier")

class AdminUser(BaseModel):
    username: str
    password_hash: str

# You can extend with more models as needed
