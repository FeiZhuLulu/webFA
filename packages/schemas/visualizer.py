from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from schemas.browser import BrowserAuthState, BrowserState
from schemas.web import TakeoverReason, WebState


class VisualizerRuntimeInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    online: bool = True
    driver: str = "managed-chromium"
    headless: bool = False
    host_status: str = "not_started"
    visible_window: bool = False


class VisualizerAgentInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active_agent_id: str | None = None
    lease_expires_at: str | None = None


class VisualizerProfileInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str = "default"
    shared: bool = True


class VisualizerPageInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = ""
    title: str = ""
    status: Literal["idle", "loading"] = "idle"
    auth: BrowserAuthState = BrowserAuthState()


class VisualizerAuthSurface(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active: bool = False
    url: str | None = None
    mode: Literal["electron", "legacy"] = "electron"


class VisualizerTakeoverSurface(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active: bool = False
    url: str | None = None
    mode: Literal["electron", "legacy"] = "electron"
    reason: TakeoverReason | None = None
    target: str | None = None
    origin: str = ""


class VisualizerPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: Literal["png"] = "png"
    data_url: str | None = None
    captured_at: str | None = None


class VisualizerActionEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: str
    tool: str
    status: Literal["ok", "error"] = "ok"
    code: str | None = None
    message: str = ""
    agent_id: str | None = None


class VisualizerError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str


class VisualizerState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runtime: VisualizerRuntimeInfo = VisualizerRuntimeInfo()
    agent: VisualizerAgentInfo = VisualizerAgentInfo()
    profile: VisualizerProfileInfo = VisualizerProfileInfo()
    page: VisualizerPageInfo = VisualizerPageInfo()
    browser_state: BrowserState | None = None
    web_state: WebState | None = None
    preview: VisualizerPreview = VisualizerPreview()
    auth_surface: VisualizerAuthSurface = VisualizerAuthSurface()
    takeover_surface: VisualizerTakeoverSurface = VisualizerTakeoverSurface()
    recent_actions: list[VisualizerActionEntry] = Field(default_factory=list)
    errors: list[VisualizerError] = Field(default_factory=list)