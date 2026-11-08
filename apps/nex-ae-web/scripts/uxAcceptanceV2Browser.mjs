export async function evaluateUxAcceptanceV2Page(
  page,
  { profile, viewport, requestUrls = [] },
) {
  return page.evaluate(async input => {
    const acceptance = await import("/src/acceptance/uxAcceptanceV2.ts");
    const focusRulePresent = Array.from(document.styleSheets).some(sheet =>
      stylesheetContainsFocusVisible(sheet),
    );
    const snapshot = acceptance.captureUxAcceptanceV2Snapshot({
      document,
      profile: input.profile,
      viewport: input.viewport,
      requestUrls: input.requestUrls,
      focusIndicatorMissingCount: focusRulePresent ? 0 : 1,
      primaryRegionOverlapCount: countPrimaryRegionOverlaps(),
    });
    return acceptance.evaluateUxAcceptanceV2(snapshot);

    function stylesheetContainsFocusVisible(sheet) {
      try {
        return rulesContainFocusVisible(Array.from(sheet.cssRules ?? []));
      } catch {
        return false;
      }
    }

    function rulesContainFocusVisible(rules) {
      return rules.some(rule => {
        if (typeof rule.selectorText === "string" && rule.selectorText.includes(":focus-visible")) return true;
        return rule.cssRules ? rulesContainFocusVisible(Array.from(rule.cssRules)) : false;
      });
    }

    function countPrimaryRegionOverlaps() {
      const elements = Array.from(document.querySelectorAll(
        '[data-ux-region="context"], [data-ux-region="composer"], [data-ux-region="primary-result"]',
      )).filter(element => {
        const style = getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
      });
      let count = 0;
      for (let left = 0; left < elements.length; left += 1) {
        for (let right = left + 1; right < elements.length; right += 1) {
          if (elements[left].contains(elements[right]) || elements[right].contains(elements[left])) continue;
          const a = elements[left].getBoundingClientRect();
          const b = elements[right].getBoundingClientRect();
          const overlapWidth = Math.min(a.right, b.right) - Math.max(a.left, b.left);
          const overlapHeight = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
          if (overlapWidth > 1 && overlapHeight > 1) count += 1;
        }
      }
      return count;
    }
  }, { profile, viewport, requestUrls });
}

export async function verifyKeyboardFocusVisible(page) {
  await page.keyboard.press("Tab");
  return page.evaluate(() => {
    const active = document.activeElement;
    if (!(active instanceof HTMLElement) || active === document.body) return false;
    const style = getComputedStyle(active);
    return style.outlineStyle !== "none" && Number.parseFloat(style.outlineWidth) >= 2;
  });
}
