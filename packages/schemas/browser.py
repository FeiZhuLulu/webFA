from __future__ import annotations

from urllib.parse import parse_qs, urlparse
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


BrowserActionName = Literal[
    "click",
    "type",
    "clear",
    "focus",
    "press",
    "select",
    "check",
    "uncheck",
    "scroll",
    "wait",
    "wait_for_text",
    "wait_for_element",
    "fill_form",
    "submit_form",
    "follow_link",
    "activate_control",
    "choose_option",
    "read_list",
    "inspect_block",
]

ContentBlockType = Literal[
    "heading",
    "paragraph",
    "list_item",
    "form",
    "nav",
    "generic",
]


class BrowserContentBlock(BaseModel):
    """A readable text block with the element ids inside it.

    Agents read content_blocks to get page structure that is more stable
    than a single flat visible_text blob. The element_ids point at the
    interactive elements inside this block so an agent can act without
    re-reading the whole page.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    type: ContentBlockType
    text: str
    element_ids: list[str] = []


class BrowserOpenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        if not value.startswith(("http://", "https://", "file://")):
            raise ValueError("url must start with http://, https://, or file://")
        return value


class BrowserActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: BrowserActionName
    target: str | None = None
    text: str | None = None
    value: str | None = None
    fields: dict[str, str] | None = None
    key: str | None = None
    ms: int | None = Field(default=None, ge=0, le=30000)
    timeout_ms: int | None = Field(default=None, ge=0, le=30000)
    state: Literal["visible", "hidden", "enabled"] | None = None
    delta_y: int | None = Field(default=None, ge=-5000, le=5000)

    @model_validator(mode="after")
    def validate_shape(self) -> "BrowserActionRequest":
        target_actions = {"click", "type", "clear", "focus", "select", "check", "uncheck"}
        if self.action in target_actions and not self.target:
            raise ValueError(f"{self.action} requires target")
        if self.action == "type" and self.text is None:
            raise ValueError("type requires text")
        if self.action == "select" and self.value is None and self.text is None:
            raise ValueError("select requires value or text")
        if self.action == "press" and not self.key:
            raise ValueError("press requires key")
        if self.action == "wait" and self.ms is None:
            raise ValueError("wait requires ms")
        if self.action == "wait_for_text" and not self.text:
            raise ValueError("wait_for_text requires text")
        if self.action == "wait_for_element" and (not self.target or not self.state):
            raise ValueError("wait_for_element requires target and state")
        if self.action == "fill_form" and (not self.target or not self.fields):
            raise ValueError("fill_form requires target and fields")
        if self.action in {"submit_form", "follow_link", "activate_control", "read_list", "inspect_block"} and not self.target:
            raise ValueError(f"{self.action} requires target")
        if self.action == "choose_option" and (not self.target or (self.value is None and self.text is None)):
            raise ValueError("choose_option requires target and value or text")
        return self


class BrowserTab(BaseModel):
    id: str
    url: str
    title: str
    active: bool


class BrowserViewport(BaseModel):
    width: int
    height: int


class BrowserUrlParts(BaseModel):
    scheme: str = ""
    host: str = ""
    origin: str = ""
    path: str = ""
    query: dict[str, str] = {}


def parse_browser_url_parts(url: str) -> BrowserUrlParts:
    parsed = urlparse(url)
    return BrowserUrlParts(
        scheme=parsed.scheme,
        host=parsed.netloc,
        origin=f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else "",
        path=parsed.path,
        query={key: values[0] for key, values in parse_qs(parsed.query, keep_blank_values=True).items()},
    )


class BrowserElement(BaseModel):
    id: str
    role: str
    tag: str
    name: str
    text: str = ""
    value: str = ""
    placeholder: str = ""
    input_type: str | None = None
    visible: bool
    enabled: bool
    checked: bool | None = None
    selected: bool | None = None
    href: str | None = None
    actions: list[str]


class BrowserFormField(BaseModel):
    id: str
    key: str
    label: str = ""
    name: str = ""
    placeholder: str = ""
    value: str = ""
    type: str | None = None
    required: bool = False
    enabled: bool = True


class BrowserForm(BaseModel):
    id: str
    label: str = ""
    text: str = ""
    fields: list[str] = []
    field_details: list[BrowserFormField] = []
    submit: str | None = None


class BrowserState(BaseModel):
    session_id: str = "default"
    url: str = ""
    url_parts: BrowserUrlParts = BrowserUrlParts()
    title: str = ""
    page_status: Literal["idle", "loading"] = "idle"
    focused_element_id: str | None = None
    viewport: BrowserViewport = BrowserViewport(width=1280, height=720)
    tabs: list[BrowserTab] = []
    visible_text: str = ""
    content_blocks: list[BrowserContentBlock] = []
    forms: list[BrowserForm] = []
    interactive_elements: list[BrowserElement] = []
    error: dict | None = None


class BrowserActionResult(BaseModel):
    ok: bool
    action: str
    state: BrowserState
    data: dict | None = None
