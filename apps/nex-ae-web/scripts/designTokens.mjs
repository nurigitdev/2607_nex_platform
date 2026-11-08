const COLOR_PATTERN = /^#[0-9A-F]{6}$/;
const DIMENSION_PATTERN = /^\d+(?:\.\d+)?(?:px|ms)$/;

export function validateDesignTokens(tokens) {
  assertObject(tokens, "tokens");
  const primitives = flattenPrimitives(tokens.primitive);
  const semanticEntries = Object.entries(assertObject(tokens.semantic, "semantic"));
  const variableNames = new Set();

  for (const [name, value] of primitives) {
    assertColor(value, `primitive.${name}`);
    addVariable(variableNames, name);
  }

  for (const [name, token] of semanticEntries) {
    assertObject(token, `semantic.${name}`);
    for (const theme of ["light", "dark"]) {
      assertColor(token[theme], `semantic.${name}.${theme}`);
      const reference = requiredText(token.ref?.[theme], `semantic.${name}.ref.${theme}`);
      if (!primitives.has(reference)) {
        throw new Error(`semantic.${name}.${theme} references an unknown primitive`);
      }
      if (token[theme] !== primitives.get(reference)) {
        throw new Error(`semantic.${name}.${theme} does not match its primitive`);
      }
    }
    addVariable(variableNames, name);
  }

  validateTypography(tokens.typography, variableNames);
  validateNumericGroup(tokens.space, "space", variableNames);
  validateNumericGroup(tokens.radius, "radius", variableNames);
  validateStringGroup(tokens.shadow, "shadow", variableNames);
  validateStringGroup(tokens.motion, "motion", variableNames);
  validateNumericGroup(tokens["z-index"], "z-index", variableNames);
  validateLayout(tokens.layout, variableNames);
  validateComponents(tokens.component);

  return Object.freeze({
    primitiveCount: primitives.size,
    semanticCount: semanticEntries.length,
    cssVariableCount: variableNames.size,
    componentCount: tokens.component.length,
  });
}

export function generateDesignTokenCss(tokens) {
  validateDesignTokens(tokens);
  const primitives = flattenPrimitives(tokens.primitive);
  const lines = [
    `/* ${requiredText(tokens.$schema_note, "$schema_note")}. Generated from tokens.json. */`,
    ":root {",
    "  /* primitive */",
  ];

  for (const [name, value] of primitives) {
    lines.push(`  --nex-${name}: ${value};`);
  }

  lines.push("", "  /* semantic (light) */");
  for (const [name, token] of Object.entries(tokens.semantic)) {
    lines.push(`  --nex-${name}: var(--nex-${token.ref.light});`);
  }

  lines.push("", "  /* typography */");
  for (const [name, value] of Object.entries(tokens.typography["font-family"])) {
    lines.push(`  --nex-font-${name}: ${value};`);
  }
  for (const [name, value] of Object.entries(tokens.typography.weight)) {
    lines.push(`  --nex-weight-${name}: ${value};`);
  }
  for (const [name, value] of Object.entries(tokens.typography.scale)) {
    const family = name === "code" ? "mono" : "sans";
    lines.push(
      `  --nex-text-${name}: ${value.weight} ${value.size}px/${value["line-height"]}px var(--nex-font-${family});`,
    );
  }

  lines.push("", "  /* space · radius · shadow · motion · z-index · layout */");
  appendNumericVariables(lines, tokens.space, "px");
  appendNumericVariables(lines, tokens.radius, "px");
  appendRawVariables(lines, tokens.shadow);
  appendRawVariables(lines, tokens.motion);
  appendRawVariables(lines, tokens["z-index"]);
  appendRawVariables(
    lines,
    Object.fromEntries(
      Object.entries(tokens.layout).filter(([name]) => !name.startsWith("bp-")),
    ),
  );
  lines.push("  color-scheme: light;", "}", "");

  lines.push(
    "/* dark: follows OS unless the user forced light */",
    "@media (prefers-color-scheme: dark) {",
    '  :root:not([data-theme="light"]) {',
  );
  appendDarkTheme(lines, tokens, "    ");
  lines.push("  }", "}", "");

  lines.push('/* dark: explicit user choice */', ':root[data-theme="dark"] {');
  appendDarkTheme(lines, tokens, "  ");
  lines.push("}", "");

  lines.push(
    "@media (prefers-reduced-motion: reduce) {",
    "  :root { --nex-duration-fast: 0ms; --nex-duration-base: 0ms; --nex-duration-slow: 0ms; }",
    "}",
    "",
  );

  const layout = tokens.layout;
  lines.push(
    `/* breakpoints (use in media queries): sm ${layout["bp-sm"]} · md ${layout["bp-md"]} · lg ${layout["bp-lg"]} · xl ${layout["bp-xl"]} */`,
  );
  return `${lines.join("\n")}\n`;
}

export function contrastRatio(foreground, background) {
  const light = relativeLuminance(foreground);
  const dark = relativeLuminance(background);
  return (Math.max(light, dark) + 0.05) / (Math.min(light, dark) + 0.05);
}

export function resolveSemanticColor(tokens, name, theme) {
  const semantic = tokens.semantic?.[name];
  if (!semantic || !["light", "dark"].includes(theme)) {
    throw new Error("Unknown semantic color request");
  }
  return semantic[theme];
}

function flattenPrimitives(source) {
  assertObject(source, "primitive");
  const result = new Map();
  for (const [name, value] of Object.entries(source)) {
    if (typeof value === "string") {
      result.set(name, value);
      continue;
    }
    assertObject(value, `primitive.${name}`);
    for (const [step, color] of Object.entries(value)) {
      result.set(`${name}-${step}`, color);
    }
  }
  return result;
}

function appendNumericVariables(lines, values, unit) {
  for (const [name, value] of Object.entries(values)) {
    lines.push(`  --nex-${name}: ${value}${unit};`);
  }
}

function appendRawVariables(lines, values) {
  for (const [name, value] of Object.entries(values)) {
    lines.push(`  --nex-${name}: ${value};`);
  }
}

function appendDarkTheme(lines, tokens, indent) {
  lines.push(`${indent}color-scheme: dark;`);
  for (const [name, token] of Object.entries(tokens.semantic)) {
    lines.push(`${indent}--nex-${name}: var(--nex-${token.ref.dark});`);
  }
  const [red, green, blue] = hexChannels(tokens.primitive.blue["400"]);
  lines.push(`${indent}--nex-focus-ring: 0 0 0 3px rgba(${red},${green},${blue},.40);`);
}

function validateTypography(typography, variableNames) {
  assertObject(typography, "typography");
  const families = assertObject(typography["font-family"], "typography.font-family");
  const weights = assertObject(typography.weight, "typography.weight");
  const scale = assertObject(typography.scale, "typography.scale");
  for (const [name, value] of Object.entries(families)) {
    requiredText(value, `typography.font-family.${name}`);
    addVariable(variableNames, `font-${name}`);
  }
  for (const [name, value] of Object.entries(weights)) {
    if (!Number.isInteger(value) || value < 100 || value > 900) {
      throw new Error(`typography.weight.${name} is invalid`);
    }
    addVariable(variableNames, `weight-${name}`);
  }
  for (const [name, value] of Object.entries(scale)) {
    assertObject(value, `typography.scale.${name}`);
    for (const field of ["size", "line-height", "weight"]) {
      if (!Number.isInteger(value[field]) || value[field] <= 0) {
        throw new Error(`typography.scale.${name}.${field} is invalid`);
      }
    }
    addVariable(variableNames, `text-${name}`);
  }
}

function validateNumericGroup(source, context, variableNames) {
  assertObject(source, context);
  for (const [name, value] of Object.entries(source)) {
    if (!Number.isInteger(value) || value < 0) {
      throw new Error(`${context}.${name} is invalid`);
    }
    addVariable(variableNames, name);
  }
}

function validateStringGroup(source, context, variableNames) {
  assertObject(source, context);
  for (const [name, value] of Object.entries(source)) {
    requiredText(value, `${context}.${name}`);
    addVariable(variableNames, name);
  }
}

function validateLayout(layout, variableNames) {
  assertObject(layout, "layout");
  for (const [name, value] of Object.entries(layout)) {
    if (!DIMENSION_PATTERN.test(value)) {
      throw new Error(`layout.${name} is invalid`);
    }
    if (!name.startsWith("bp-")) addVariable(variableNames, name);
  }
}

function validateComponents(components) {
  if (!Array.isArray(components) || components.length === 0) {
    throw new Error("component definitions are required");
  }
  const names = new Set();
  for (const component of components) {
    assertObject(component, "component");
    const name = requiredText(component.name, "component.name");
    if (names.has(name)) throw new Error(`Duplicate component token: ${name}`);
    names.add(name);
  }
}

function addVariable(variableNames, name) {
  const variable = `--nex-${name}`;
  if (variableNames.has(variable)) {
    throw new Error(`Duplicate CSS variable: ${variable}`);
  }
  variableNames.add(variable);
}

function assertColor(value, context) {
  if (typeof value !== "string" || !COLOR_PATTERN.test(value)) {
    throw new Error(`${context} must be a six-digit uppercase hex color`);
  }
}

function assertObject(value, context) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${context} must be an object`);
  }
  return value;
}

function requiredText(value, context) {
  if (typeof value !== "string" || !value.trim()) {
    throw new Error(`${context} must be non-empty text`);
  }
  return value.trim();
}

function relativeLuminance(hex) {
  const channels = hexChannels(hex).map(channel => {
    const normalized = channel / 255;
    return normalized <= 0.04045
      ? normalized / 12.92
      : ((normalized + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
}

function hexChannels(hex) {
  assertColor(hex, "color");
  return [1, 3, 5].map(index => Number.parseInt(hex.slice(index, index + 2), 16));
}
