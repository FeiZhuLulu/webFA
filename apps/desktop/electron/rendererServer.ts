import { createReadStream, promises as fs } from "fs";
import { createServer, IncomingMessage, Server, ServerResponse } from "http";
import path from "path";

const LOOPBACK_HOST = "127.0.0.1";
const CONTENT_TYPES: Record<string, string> = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".ico": "image/x-icon",
  ".jpeg": "image/jpeg",
  ".jpg": "image/jpeg",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".map": "application/json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".txt": "text/plain; charset=utf-8",
  ".webp": "image/webp",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
};

function isPathWithin(root: string, candidate: string): boolean {
  const relative = path.relative(root, candidate);
  return (
    relative === "" ||
    (relative !== ".." &&
      !relative.startsWith(`..${path.sep}`) &&
      !path.isAbsolute(relative))
  );
}

interface RendererAssetServerOptions {
  integrityProtectedArchive?: string;
}

export class RendererAssetServer {
  private readonly root: string;
  private readonly integrityProtectedArchive: string | null;
  private realRoot: string | null = null;
  private server: Server | null = null;
  private currentOrigin: string | null = null;

  constructor(root: string, options: RendererAssetServerOptions = {}) {
    this.root = path.resolve(root);
    const archive = options.integrityProtectedArchive;
    if (archive === undefined) {
      this.integrityProtectedArchive = null;
      return;
    }
    const resolvedArchive = path.resolve(archive);
    if (path.extname(resolvedArchive).toLowerCase() !== ".asar") {
      throw new Error("Integrity-protected renderer archive must be an ASAR file");
    }
    if (this.root === resolvedArchive || !isPathWithin(resolvedArchive, this.root)) {
      throw new Error("Renderer asset root is outside the integrity-protected archive");
    }
    this.integrityProtectedArchive = resolvedArchive;
  }

  get origin(): string | null {
    return this.currentOrigin;
  }

  async start(): Promise<string> {
    if (this.server && this.currentOrigin) return this.currentOrigin;
    if (this.integrityProtectedArchive) {
      // Packaged renderer files are covered by Electron's embedded ASAR integrity
      // fuse, and the release verifier rejects every ASAR link. Reading them
      // directly avoids Electron's deprecated fs.Stats ASAR metadata bridge.
      this.realRoot = null;
    } else {
      const realRoot = await fs.realpath(this.root);
      const rootStat = await fs.stat(realRoot);
      if (!rootStat.isDirectory()) {
        throw new Error("Renderer asset root is not a directory");
      }
      this.realRoot = realRoot;
    }
    try {
      await Promise.all([
        this.assertRequiredFile("index.html"),
        this.assertRequiredFile(path.join("monitor", "index.html")),
      ]);
    } catch (error) {
      this.realRoot = null;
      throw error;
    }

    const server = createServer((request, response) => {
      void this.handle(request, response).catch(() => {
        if (!response.headersSent) this.writePlain(response, 500, "Internal renderer error");
        else response.destroy();
      });
    });
    this.server = server;

    try {
      await new Promise<void>((resolve, reject) => {
        server.once("error", reject);
        server.listen(0, LOOPBACK_HOST, () => {
          server.off("error", reject);
          resolve();
        });
      });
    } catch (error) {
      this.server = null;
      this.realRoot = null;
      throw error;
    }

    const address = server.address();
    if (!address || typeof address === "string") {
      await this.stop();
      throw new Error("Renderer asset server did not receive a loopback TCP address");
    }
    this.currentOrigin = `http://${LOOPBACK_HOST}:${address.port}`;
    return this.currentOrigin;
  }

  async stop(): Promise<void> {
    const server = this.server;
    this.server = null;
    this.currentOrigin = null;
    this.realRoot = null;
    if (!server) return;
    await new Promise<void>((resolve, reject) => {
      server.close((error) => (error ? reject(error) : resolve()));
      server.closeAllConnections?.();
    });
  }

  private async handle(request: IncomingMessage, response: ServerResponse): Promise<void> {
    const method = request.method ?? "GET";
    if (method !== "GET" && method !== "HEAD") {
      response.setHeader("Allow", "GET, HEAD");
      this.writePlain(response, 405, "Method not allowed");
      return;
    }

    let pathname: string;
    try {
      pathname = decodeURIComponent(new URL(request.url ?? "/", "http://renderer.invalid").pathname);
    } catch {
      this.writePlain(response, 400, "Invalid asset path");
      return;
    }
    if (pathname.includes("\0") || pathname.includes("\\")) {
      this.writePlain(response, 400, "Invalid asset path");
      return;
    }

    if (pathname !== "/" && !pathname.endsWith("/") && path.posix.extname(pathname) === "") {
      response.statusCode = 308;
      response.setHeader("Location", `${pathname}/${new URL(request.url ?? "/", "http://renderer.invalid").search}`);
      this.setSecurityHeaders(response);
      response.end();
      return;
    }

    const relativePath = pathname === "/"
      ? "index.html"
      : pathname.endsWith("/")
        ? `${pathname.slice(1)}index.html`
        : pathname.slice(1);
    const candidate = path.resolve(this.root, relativePath);
    if (!isPathWithin(this.root, candidate)) {
      this.writePlain(response, 403, "Asset path is outside the renderer root");
      return;
    }

    if (this.integrityProtectedArchive) {
      let body: Buffer;
      try {
        body = await fs.readFile(candidate);
      } catch {
        this.writePlain(response, 404, "Asset not found");
        return;
      }
      this.writeAssetHeaders(response, pathname, candidate, body.length);
      if (method === "HEAD") response.end();
      else response.end(body);
      return;
    }

    let realCandidate: string;
    try {
      realCandidate = await fs.realpath(candidate);
    } catch {
      this.writePlain(response, 404, "Asset not found");
      return;
    }
    if (!this.realRoot || !isPathWithin(this.realRoot, realCandidate)) {
      this.writePlain(response, 403, "Asset path is outside the renderer root");
      return;
    }

    let stat;
    try {
      stat = await fs.stat(realCandidate);
    } catch {
      this.writePlain(response, 404, "Asset not found");
      return;
    }
    if (!stat.isFile()) {
      this.writePlain(response, 404, "Asset not found");
      return;
    }

    this.writeAssetHeaders(response, pathname, candidate, stat.size);
    if (method === "HEAD") {
      response.end();
      return;
    }
    createReadStream(realCandidate).on("error", () => response.destroy()).pipe(response);
  }

  private async assertRequiredFile(relativePath: string): Promise<void> {
    const candidate = path.resolve(this.root, relativePath);
    if (!isPathWithin(this.root, candidate)) {
      throw new Error(`Required renderer asset is outside the renderer root: ${relativePath}`);
    }
    if (this.integrityProtectedArchive) {
      await fs.readFile(candidate);
      return;
    }
    if (!this.realRoot) throw new Error("Renderer asset root is unavailable");
    const realCandidate = await fs.realpath(candidate);
    if (!isPathWithin(this.realRoot, realCandidate)) {
      throw new Error(`Required renderer asset is outside the renderer root: ${relativePath}`);
    }
    const stat = await fs.stat(realCandidate);
    if (!stat.isFile()) {
      throw new Error(`Required renderer asset is not a file: ${relativePath}`);
    }
  }

  private writeAssetHeaders(
    response: ServerResponse,
    pathname: string,
    candidate: string,
    contentLength: number,
  ): void {
    response.statusCode = 200;
    response.setHeader("Content-Type", CONTENT_TYPES[path.extname(candidate).toLowerCase()] ?? "application/octet-stream");
    response.setHeader("Content-Length", String(contentLength));
    response.setHeader(
      "Cache-Control",
      pathname.startsWith("/_next/static/") ? "public, max-age=31536000, immutable" : "no-store",
    );
    this.setSecurityHeaders(response);
  }

  private writePlain(response: ServerResponse, status: number, message: string): void {
    const body = Buffer.from(message, "utf8");
    response.statusCode = status;
    response.setHeader("Content-Type", "text/plain; charset=utf-8");
    response.setHeader("Content-Length", String(body.length));
    response.setHeader("Cache-Control", "no-store");
    this.setSecurityHeaders(response);
    response.end(body);
  }

  private setSecurityHeaders(response: ServerResponse): void {
    response.setHeader("Content-Security-Policy", [
      "default-src 'self'",
      "base-uri 'none'",
      "connect-src 'self' http://127.0.0.1:* http://localhost:* ws://127.0.0.1:* ws://localhost:*",
      "font-src 'self' data:",
      "form-action 'none'",
      "frame-ancestors 'none'",
      "img-src 'self' data: blob:",
      "object-src 'none'",
      "script-src 'self' 'unsafe-inline'",
      "style-src 'self' 'unsafe-inline'",
      "worker-src 'self' blob:",
    ].join("; "));
    response.setHeader("Cross-Origin-Opener-Policy", "same-origin");
    response.setHeader("Referrer-Policy", "no-referrer");
    response.setHeader("X-Content-Type-Options", "nosniff");
    response.setHeader("X-Frame-Options", "DENY");
  }
}
