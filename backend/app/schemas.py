from pydantic import BaseModel, Field
from typing import List, Optional

class ColorWithAlpha(BaseModel):
    hex: str = Field(..., pattern=r"^#([A-Fa-f0-9]{6})$")
    alpha: float = Field(1.0, ge=0.0, le=1.0)

class FormDataIn(BaseModel):
    aspectRatio: str
    primaryColors: List[ColorWithAlpha]
    theme: str
    customTheme: Optional[str] = ""
    includeText: bool
    text: Optional[str] = ""
    fontFamily: str
    backgroundColor: ColorWithAlpha
    style: str
    referenceImageBase64: Optional[str] = None

class PromptOut(BaseModel):
    prompt: dict
