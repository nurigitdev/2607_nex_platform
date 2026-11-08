export async function activateAuthenticatedView(page, view, { timeoutMs } = {}) {
  if (typeof page?.click !== "function") return;
  await page.waitForSelector("#authenticated-shell:not([hidden])", {
    ...(timeoutMs ? { timeout: timeoutMs } : {})
  });
  await page.click(`[data-shell-view="${view}"]`);
}
