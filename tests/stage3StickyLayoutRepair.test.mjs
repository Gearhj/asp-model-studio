import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const ROOT = new URL("..", import.meta.url);
const read = (path) => readFile(new URL(path, ROOT), "utf8");

const [app, cockpit, profile, gallery, css] = await Promise.all([
  read("src/apps/ModelingApp.tsx"),
  read("src/sports/cockpit/PaModelingCockpit.tsx"),
  read("src/sports/cockpit/ProjectBoundDataProfile.tsx"),
  read("src/sports/cockpit/Stage3DistributionGallery.tsx"),
  read("src/index.css"),
]);

function sectionOpening(source, testId) {
  const marker = `data-testid="${testId}"`;
  const index = source.indexOf(marker);
  assert.notEqual(index, -1, `missing ${testId}`);
  return source.slice(Math.max(0, source.lastIndexOf("<section", index)), index + marker.length);
}

test("one shared shell declares responsive chrome offsets for focus and ordinary Stage 3", () => {
  assert.ok(app.includes('data-stage3-app-shell={focusRoute.stage3SurfaceActive ? "active" : undefined}'));
  assert.match(css, /\[data-stage3-app-shell="active"\]\s*\{\s*--stage3-shell-chrome-offset:\s*8\.25rem/);
  assert.match(css, /\[data-stage3-app-shell="active"\]\[data-stage3-focus-mode="active"\]\s*\{\s*--stage3-shell-chrome-offset:\s*4rem/);
  assert.match(css, /@media \(min-width: 1024px\)[\s\S]*--stage3-shell-chrome-offset:\s*4\.25rem[\s\S]*--stage3-shell-chrome-offset:\s*0px/);
});

test("the single compact header measures itself and the canvas reserves exact scroll clearance", () => {
  for (const token of [
    "headerRef",
    "ResizeObserver",
    "getBoundingClientRect().height",
    '"--stage3-compact-header-height"',
    'style={{ top: "var(--stage3-shell-chrome-offset, 0px)" }}',
    "stage3-scroll-target",
  ]) assert.ok(cockpit.includes(token), `missing measured-header contract: ${token}`);

  assert.match(css, /\.stage3-scroll-target\s*\{[\s\S]*scroll-margin-top:\s*calc\([\s\S]*--stage3-shell-chrome-offset[\s\S]*--stage3-compact-header-height/);
  assert.ok(cockpit.includes("requestAnimationFrame(() =>"));
  assert.ok(cockpit.includes('scrollIntoView({ behavior: "smooth", block: "start" })'));
});

test("all fifteen steps render below the same bounded workspace and analytical canvas", () => {
  const stepIds = [...cockpit.matchAll(/\{ id: "([a-z]+)", n: "\d\d"/g)].map((match) => match[1]);
  assert.equal(stepIds.length, 15);
  assert.ok(cockpit.includes("stage3-focus-workspace min-w-0 max-w-full"));
  assert.ok(cockpit.includes("overflow-x-clip"));
  assert.ok(cockpit.includes("stage3-scroll-target min-w-0 max-w-full"));
  assert.match(css, /\.stage3-focus-workspace\s*\{[\s\S]*max-width:\s*100%;[\s\S]*overflow-x:\s*clip/);
});

test("page-specific Data Profile controls no longer create stacked sticky overlays", () => {
  const profileControls = sectionOpening(profile, "stage3-eda-sticky-controls");
  const galleryControls = sectionOpening(gallery, "stage3-gallery-local-controls");
  const profileClasses = profileControls.match(/className="([^"]*)"/)?.[1] ?? "";
  const galleryClasses = galleryControls.match(/className="([^"]*)"/)?.[1] ?? "";
  assert.ok(profileControls.includes("stage3-flow-controls"));
  assert.ok(galleryControls.includes("stage3-flow-controls"));
  assert.doesNotMatch(profileClasses, /\bsticky\b|top-\[/);
  assert.doesNotMatch(galleryClasses, /\bsticky\b|top-\[/);
  assert.match(css, /\.stage3-flow-controls\s*\{\s*position:\s*relative/);
});
