from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from schemas.browser import (
    BrowserAgentState,
    BrowserAuthState,
    BrowserDialog,
    BrowserFrame,
    BrowserStateError,
    BrowserUrlSecurity,
)


ObjectCategory = Literal[
    "document",
    "container",
    "content",
    "interactive",
    "collection",
    "dialog",
    "frame",
    "resource",
    "opaque_surface",
]

ObjectRole = Literal[
    "document",
    "main",
    "region",
    "navigation",
    "header",
    "footer",
    "section",
    "article",
    "complementary",
    "heading",
    "paragraph",
    "text",
    "code",
    "quote",
    "image",
    "figure",
    "link",
    "button",
    "field",
    "searchbox",
    "textbox",
    "textarea",
    "checkbox",
    "radio",
    "switch",
    "combobox",
    "option",
    "slider",
    "tab",
    "menu",
    "menuitem",
    "form",
    "toolbar",
    "upload_target",
    "collection",
    "list",
    "list_item",
    "table",
    "row",
    "cell",
    "column_header",
    "row_header",
    "tree",
    "tree_item",
    "feed",
    "dialog",
    "alert",
    "status",
    "tooltip",
    "frame",
    "download",
    "media",
    "resource",
    "opaque_surface",
]

ObjectLifetime = Literal["runtime", "session", "document", "frame", "transient"]
ContentTrust = Literal["untrusted", "user_provided", "trusted_runtime"]

ObjectCapabilityName = Literal[
    "open",
    "open_in_new_context",
    "activate",
    "set_value",
    "clear_value",
    "choose",
    "toggle",
    "submit",
    "expand",
    "collapse",
    "dismiss",
    "download",
    "upload",
    "request_human_takeover",
]

SemanticOperationName = ObjectCapabilityName

CapabilityEffect = Literal[
    "read",
    "navigation",
    "local_state_change",
    "external_write",
    "external_send",
    "download",
    "upload",
    "destructive",
    "permission_change",
    "unknown",
]

CapabilityArgumentType = Literal[
    "string",
    "integer",
    "number",
    "boolean",
    "object",
    "array",
]

ObserveMode = Literal["page", "object", "query", "changes"]
ObserveDetail = Literal["summary", "standard", "full", "debug"]
WebStateStatus = Literal["idle", "loading", "error"]
TakeoverReason = Literal[
    "authentication",
    "captcha",
    "opaque_surface",
    "high_risk_confirmation",
    "permission_request",
    "file_selection",
    "ambiguous_state",
    "manual_identity_confirmation",
]

WebScalar = str | int | float | bool
WebValue = WebScalar | list[WebScalar] | None


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WebVisibleRange(StrictModel):
    start: int = Field(ge=0)
    end: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_order(self) -> "WebVisibleRange":
        if self.end < self.start:
            raise ValueError("end must be greater than or equal to start")
        return self


class WebObjectRange(StrictModel):
    start: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=100)


class WebObjectState(StrictModel):
    visible: bool = True
    enabled: bool = True
    focused: bool = False
    selected: bool | None = None
    checked: bool | None = None
    expanded: bool | None = None
    required: bool | None = None
    readonly: bool | None = None
    busy: bool = False
    invalid: bool | None = None
    pressed: bool | None = None


class WebObjectRelations(StrictModel):
    parent: str | None = None
    children: list[str] = Field(default_factory=list)
    belongs_to: str | None = None
    labelled_by: list[str] = Field(default_factory=list)
    described_by: list[str] = Field(default_factory=list)
    controls: list[str] = Field(default_factory=list)
    controlled_by: list[str] = Field(default_factory=list)
    owns: list[str] = Field(default_factory=list)
    owned_by: str | None = None
    form: str | None = None
    submit_control: str | None = None
    fields: list[str] = Field(default_factory=list)
    items: list[str] = Field(default_factory=list)
    rows: list[str] = Field(default_factory=list)
    cells: list[str] = Field(default_factory=list)
    headers: list[str] = Field(default_factory=list)


class WebObjectObservable(StrictModel):
    inspectable: bool = True
    range_readable: bool = False
    item_count: int | None = Field(default=None, ge=0)
    visible_range: WebVisibleRange | None = None


class WebObjectSecurity(StrictModel):
    content_trust: ContentTrust = "untrusted"
    cross_origin: bool = False


class WebObjectBase(StrictModel):
    id: str = Field(min_length=1)
    category: ObjectCategory
    role: ObjectRole
    name: str = ""
    capabilities: list[ObjectCapabilityName] = Field(default_factory=list)
    version: int = Field(default=1, ge=1)


class WebObjectSummary(WebObjectBase):
    projection: Literal["summary"] = "summary"
    state_summary: list[str] = Field(default_factory=list)


class WebObject(WebObjectBase):
    projection: Literal["full"] = "full"
    description: str = ""
    text: str = ""
    value: WebValue = None
    state: WebObjectState = Field(default_factory=WebObjectState)
    relations: WebObjectRelations = Field(default_factory=WebObjectRelations)
    observable: WebObjectObservable = Field(default_factory=WebObjectObservable)
    origin: str = ""
    frame_id: str | None = None
    lifetime: ObjectLifetime = "document"
    security: WebObjectSecurity = Field(default_factory=WebObjectSecurity)
    opaque_reason: str | None = None

    @model_validator(mode="after")
    def validate_opaque_surface(self) -> "WebObject":
        is_opaque = self.category == "opaque_surface" or self.role == "opaque_surface"
        if is_opaque and not self.opaque_reason:
            raise ValueError("opaque surfaces require opaque_reason")
        if not is_opaque and self.opaque_reason is not None:
            raise ValueError("opaque_reason is only valid for opaque surfaces")
        return self


WebObjectProjection = Annotated[
    WebObjectSummary | WebObject,
    Field(discriminator="projection"),
]


class CapabilityArgumentDescriptor(StrictModel):
    type: CapabilityArgumentType
    required: bool = False
    description: str = ""
    minimum: float | None = None
    maximum: float | None = None
    enum: list[WebScalar] = Field(default_factory=list)
    properties: dict[str, "CapabilityArgumentDescriptor"] = Field(default_factory=dict)
    items: "CapabilityArgumentDescriptor | None" = None


class CapabilityDescriptor(StrictModel):
    name: ObjectCapabilityName
    arguments: dict[str, CapabilityArgumentDescriptor] = Field(default_factory=dict)
    effect: CapabilityEffect = "unknown"
    requires_confirmation: bool = False
    description: str = ""


class WebOutlineItem(StrictModel):
    object_id: str
    level: int = Field(ge=1, le=6)
    name: str = ""


class WebRegionRef(StrictModel):
    object_id: str
    role: ObjectRole
    name: str = ""


class WebObjectUpdate(StrictModel):
    id: str
    from_version: int = Field(ge=1)
    to_version: int = Field(ge=1)
    changed_fields: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_version_order(self) -> "WebObjectUpdate":
        if self.to_version <= self.from_version:
            raise ValueError("to_version must be greater than from_version")
        return self


class WebChangeSet(StrictModel):
    from_revision: int = Field(ge=0)
    to_revision: int = Field(ge=0)
    document_changed_fields: list[str] = Field(default_factory=list)
    added: list[WebObjectSummary] = Field(default_factory=list)
    updated: list[WebObjectUpdate] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    invalidated: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_revision_order(self) -> "WebChangeSet":
        if self.to_revision < self.from_revision:
            raise ValueError("to_revision must be greater than or equal to from_revision")
        return self


class HumanTakeoverState(StrictModel):
    required: bool = False
    reason: TakeoverReason | None = None
    target: str | None = None
    origin: str = ""
    resume_operation: Literal["observe"] = "observe"

    @model_validator(mode="after")
    def validate_required_reason(self) -> "HumanTakeoverState":
        if self.required and self.reason is None:
            raise ValueError("required takeover needs a reason")
        if not self.required and self.reason is not None:
            raise ValueError("takeover reason requires required=true")
        return self


class WebObserveQuery(StrictModel):
    id: str | None = None
    category: ObjectCategory | None = None
    role: ObjectRole | None = None
    name: str | None = None
    name_contains: str | None = None
    text_contains: str | None = None
    within: str | None = None
    capability: ObjectCapabilityName | None = None
    visible: bool | None = None
    enabled: bool | None = None
    frame_id: str | None = None
    origin: str | None = None

    @model_validator(mode="after")
    def require_filter(self) -> "WebObserveQuery":
        if not any(value is not None for value in self.__dict__.values()):
            raise ValueError("query requires at least one filter")
        return self


class WebObserveRequest(StrictModel):
    mode: ObserveMode = "page"
    target: str | None = None
    query: WebObserveQuery | None = None
    range: WebObjectRange | None = None
    since_revision: int | None = Field(default=None, ge=0)
    detail: ObserveDetail = "standard"
    limit: int = Field(default=50, ge=1, le=100)

    @model_validator(mode="after")
    def validate_mode_shape(self) -> "WebObserveRequest":
        if self.mode == "page":
            if any(value is not None for value in (self.target, self.query, self.range, self.since_revision)):
                raise ValueError("page mode does not accept target, query, range, or since_revision")
        elif self.mode == "object":
            if not self.target:
                raise ValueError("object mode requires target")
            if self.query is not None or self.since_revision is not None:
                raise ValueError("object mode does not accept query or since_revision")
        elif self.mode == "query":
            if self.query is None:
                raise ValueError("query mode requires query")
            if self.target is not None or self.range is not None or self.since_revision is not None:
                raise ValueError("query mode does not accept target, range, or since_revision")
        elif self.mode == "changes":
            if self.since_revision is None:
                raise ValueError("changes mode requires since_revision")
            if self.target is not None or self.query is not None or self.range is not None:
                raise ValueError("changes mode does not accept target, query, or range")
        return self


class WebState(StrictModel):
    session_id: str = "default"
    document_id: str = ""
    document_revision: int = Field(default=0, ge=0)
    url: str = ""
    title: str = ""
    status: WebStateStatus = "idle"
    outline: list[WebOutlineItem] = Field(default_factory=list)
    regions: list[WebRegionRef] = Field(default_factory=list)
    objects: list[WebObjectProjection] = Field(default_factory=list)
    object_count: int = Field(default=0, ge=0)
    frames: list[BrowserFrame] = Field(default_factory=list)
    dialogs: list[BrowserDialog] = Field(default_factory=list)
    auth: BrowserAuthState = Field(default_factory=BrowserAuthState)
    takeover: HumanTakeoverState = Field(default_factory=HumanTakeoverState)
    security: BrowserUrlSecurity = Field(default_factory=BrowserUrlSecurity)
    agent: BrowserAgentState = Field(default_factory=BrowserAgentState)
    changes: WebChangeSet | None = None
    errors: list[BrowserStateError] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_object_count(self) -> "WebState":
        if self.object_count < len(self.objects):
            raise ValueError("object_count cannot be smaller than returned objects")
        return self


class WebOperationRequest(StrictModel):
    target: str = Field(min_length=1)
    operation: SemanticOperationName
    arguments: dict[str, Any] = Field(default_factory=dict)
    expected_object_version: int | None = Field(default=None, ge=1)


class WebOperationResult(StrictModel):
    ok: bool
    target: str
    operation: SemanticOperationName
    previous_object_version: int | None = Field(default=None, ge=1)
    current_object_version: int | None = Field(default=None, ge=1)
    document_revision: int = Field(default=0, ge=0)
    state: WebState
    data: dict[str, Any] | None = None


CapabilityArgumentDescriptor.model_rebuild()
