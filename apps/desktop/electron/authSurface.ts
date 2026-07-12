export type AuthSurfaceBounds = {
  x: number;
  y: number;
  width: number;
  height: number;
};

export type AuthSurfaceStatus = {
  active: false;
  url: null;
  profilePath: "";
};

/**
 * Retired compatibility symbol.
 *
 * The former AuthSurface created a second Electron WebContentsView and loaded
 * the target URL again. UI-1B phase 6 forbids that architecture. Human input is
 * now forwarded through HumanControlLease to the existing BrowserHost page.
 */
export class AuthSurfaceManager {
  getProfilePath(): "" {
    return "";
  }

  getStatus(): AuthSurfaceStatus {
    return { active: false, url: null, profilePath: "" };
  }

  show(): never {
    throw new Error(
      "AuthSurface is retired; use Session Monitor HumanControlLease",
    );
  }

  hide(): AuthSurfaceStatus {
    return this.getStatus();
  }

  destroy(): AuthSurfaceStatus {
    return this.getStatus();
  }
}

export function resolveWebfaProfilePath(): "" {
  return "";
}
