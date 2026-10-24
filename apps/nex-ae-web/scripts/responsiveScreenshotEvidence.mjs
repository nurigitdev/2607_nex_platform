import { mkdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");

export async function captureResponsiveScreenshotEvidence({
  page,
  screenshotDir,
  prefix
}) {
  if (!screenshotDir) {
    return {
      requested: false,
      captureCount: 0,
      noHorizontalOverflow: true,
      layouts: []
    };
  }
  const targetDir = resolveScreenshotDir(screenshotDir);
  await mkdir(targetDir, { recursive: true });
  const originalViewport = page.viewportSize();
  let noHorizontalOverflow = true;
  let captureCount = 0;
  const layouts = [];
  for (const [name, viewport] of Object.entries({
    desktop: { width: 1440, height: 1000 },
    mobile: { width: 390, height: 844 }
  })) {
    await page.setViewportSize(viewport);
    const layout = await page.evaluate(() => {
      const viewportWidth = window.innerWidth;
      const documentWidth = document.documentElement.scrollWidth;
      const offenders = [...document.body.querySelectorAll("*")]
        .map(element => {
          const rect = element.getBoundingClientRect();
          let depth = 0;
          for (
            let parent = element.parentElement;
            parent;
            parent = parent.parentElement
          ) {
            depth += 1;
          }
          return {
            tag: element.tagName.toLowerCase(),
            id: element.id || null,
            classes: [...element.classList].slice(0, 4),
            depth,
            left: Math.round(rect.left),
            right: Math.round(rect.right),
            width: Math.round(rect.width),
            clientWidth: element.clientWidth,
            scrollWidth: element.scrollWidth
          };
        })
        .filter(
          item =>
            item.left < -1 ||
            item.right > viewportWidth + 1 ||
            item.scrollWidth > item.clientWidth + 1
        )
        .sort((left, right) => right.depth - left.depth)
        .slice(0, 12);
      return { viewportWidth, documentWidth, offenders };
    });
    layouts.push({ name, ...layout });
    noHorizontalOverflow &&= layout.documentWidth <= layout.viewportWidth + 1;
    await page.screenshot({
      path: resolve(targetDir, `${prefix}-${name}.png`),
      fullPage: true
    });
    captureCount += 1;
  }
  if (originalViewport) await page.setViewportSize(originalViewport);
  return { requested: true, captureCount, noHorizontalOverflow, layouts };
}

function resolveScreenshotDir(value) {
  const normalized = String(value).trim().replaceAll("\\", "/");
  if (
    !normalized.startsWith("reports/quality/") ||
    normalized.split("/").includes("..")
  ) {
    throw new Error("InvalidScreenshotDirectory");
  }
  return resolve(ROOT, normalized);
}
