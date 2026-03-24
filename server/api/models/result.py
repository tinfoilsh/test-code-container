from __future__ import annotations

import warnings
from typing import Optional, Iterable
from pydantic import BaseModel

from api.models.output import OutputType

warnings.filterwarnings("ignore", category=UserWarning)


class Result(BaseModel):
    type: OutputType = OutputType.RESULT

    text: Optional[str] = None
    html: Optional[str] = None
    markdown: Optional[str] = None
    svg: Optional[str] = None
    png: Optional[str] = None
    jpeg: Optional[str] = None
    pdf: Optional[str] = None
    latex: Optional[str] = None
    json: Optional[dict] = None
    javascript: Optional[str] = None
    data: Optional[dict] = None
    chart: Optional[dict] = None
    extra: Optional[dict] = None

    is_main_result: Optional[bool] = None

    def __init__(self, is_main_result: bool, data: dict):
        super().__init__()
        self.is_main_result = is_main_result

        self.text = data.pop("text/plain", None)
        if self.text and (
            (self.text.startswith("'") and self.text.endswith("'"))
            or (self.text.startswith('"') and self.text.endswith('"'))
        ):
            self.text = self.text[1:-1]

        self.html = data.pop("text/html", None)
        self.markdown = data.pop("text/markdown", None)
        self.svg = data.pop("image/svg+xml", None)
        self.png = data.pop("image/png", None)
        self.jpeg = data.pop("image/jpeg", None)
        self.pdf = data.pop("application/pdf", None)
        self.latex = data.pop("text/latex", None)
        self.json = data.pop("application/json", None)
        self.javascript = data.pop("application/javascript", None)
        self.data = data.pop("e2b/data", None)
        self.chart = data.pop("e2b/chart", None)
        self.extra = data

    def formats(self) -> Iterable[str]:
        formats = []
        for key in ["text", "html", "markdown", "svg", "png", "jpeg", "pdf",
                    "latex", "json", "javascript", "data", "chart"]:
            if getattr(self, key):
                formats.append(key)
        if self.extra:
            formats.extend(self.extra.keys())
        return formats

    def __repr__(self) -> str:
        if self.text:
            return f"Result({self.text})"
        return f"Result with formats: {self.formats()}"
