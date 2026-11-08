import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

import {
  generateDesignTokenCss,
  validateDesignTokens,
} from "./designTokens.mjs";

const tokenUrl = new URL("../src/design-system/tokens/tokens.json", import.meta.url);
const cssUrl = new URL("../src/design-system/tokens/tokens.css", import.meta.url);
const admittedCssUrl = new URL("../../../docs/transition/UIUX/tokens.css", import.meta.url);

const tokens = JSON.parse(await readFile(tokenUrl, "utf8"));
const validation = validateDesignTokens(tokens);
const generatedCss = generateDesignTokenCss(tokens);

if (process.argv.includes("--check")) {
  const [applicationCss, admittedCss] = await Promise.all([
    readFile(cssUrl, "utf8"),
    readFile(admittedCssUrl, "utf8"),
  ]);
  if (applicationCss !== generatedCss) {
    throw new Error("Application design token CSS has drifted from tokens.json");
  }
  if (admittedCss !== generatedCss) {
    throw new Error("Admitted design token CSS is not reproducible from tokens.json");
  }
  console.log(
    `design_token_check=pass variables=${validation.cssVariableCount} components=${validation.componentCount}`,
  );
} else {
  await writeFile(cssUrl, generatedCss, "utf8");
  console.log(
    `design_token_generation=pass output=${fileURLToPath(cssUrl)} variables=${validation.cssVariableCount}`,
  );
}
