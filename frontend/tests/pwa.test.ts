import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

/**
 * iOS home-screen web apps break out to Safari for any route outside the
 * manifest scope. The app previously shipped no manifest at all, so iOS fell
 * back to a narrow default scope derived from the install page (Library) and
 * opening /account escaped into a second Safari page. These tests pin the
 * whole-origin scope that keeps every SPA route in the standalone window.
 */
describe("home-screen web app scope", () => {
  const frontendDir = process.cwd();
  const manifestPath = path.join(
    frontendDir,
    "public",
    "manifest.webmanifest",
  );
  const indexHtml = fs.readFileSync(
    path.join(frontendDir, "index.html"),
    "utf8",
  );
  const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8")) as {
    id?: string;
    start_url?: string;
    scope?: string;
    display?: string;
    icons?: { src: string; sizes: string; type: string }[];
  };

  it("covers the whole origin so /account stays in-app", () => {
    expect(manifest.id).toBe("/");
    expect(manifest.start_url).toBe("/");
    expect(manifest.scope).toBe("/");
    expect(manifest.display).toBe("standalone");
  });

  it("ships the icons it references", () => {
    expect(manifest.icons?.length).toBeGreaterThan(0);
    const srcs = (manifest.icons ?? []).map((icon) => icon.src);
    expect(srcs).toContain("/icons/icon-192.png");
    expect(srcs).toContain("/icons/icon-512.png");
    for (const src of srcs) {
      const file = path.join(frontendDir, "public", src.replace(/^\//, ""));
      expect(fs.existsSync(file), `${src} must exist`).toBe(true);
    }
    expect(
      fs.existsSync(
        path.join(frontendDir, "public", "icons", "apple-touch-icon.png"),
      ),
    ).toBe(true);
  });

  it("declares the manifest and iOS standalone tags in index.html", () => {
    expect(indexHtml).toContain('rel="manifest"');
    expect(indexHtml).toContain('name="mobile-web-app-capable"');
    expect(indexHtml).toContain('name="apple-mobile-web-app-capable"');
    expect(indexHtml).toContain('rel="apple-touch-icon"');
  });
});
