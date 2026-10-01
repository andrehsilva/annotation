/**
 * As linguagens do bloco de código — as do dia a dia na frente.
 *
 * A ordem importa: o seletor mostra `PRIORITY` primeiro (python, javascript e o resto do que se
 * escreve toda hora) e o resto em ordem alfabética depois. O valor é o id do highlight.js, que é
 * quem pinta o código; `plaintext` é "sem realce" e serve para saída de log, diagrama, o que for.
 */
export const LANGUAGE_PRIORITY = [
  "python",
  "javascript",
  "typescript",
  "html",
  "css",
  "markdown",
  "json",
  "bash",
  "sql",
] as const;

export const LANGUAGES = [
  ...LANGUAGE_PRIORITY,
  "c",
  "cpp",
  "csharp",
  "diff",
  "dockerfile",
  "go",
  "ini",
  "java",
  "kotlin",
  "lua",
  "php",
  "powershell",
  "ruby",
  "rust",
  "swift",
  "xml",
  "yaml",
  "plaintext",
] as const;

/** Como a linguagem aparece no seletor e no cartão da lista por tipo. */
export const LANGUAGE_LABELS: Record<string, string> = {
  python: "Python",
  javascript: "JavaScript",
  typescript: "TypeScript",
  html: "HTML",
  css: "CSS",
  markdown: "Markdown",
  json: "JSON",
  bash: "Shell",
  sql: "SQL",
  c: "C",
  cpp: "C++",
  csharp: "C#",
  diff: "Diff",
  dockerfile: "Dockerfile",
  go: "Go",
  ini: "INI/TOML",
  java: "Java",
  kotlin: "Kotlin",
  lua: "Lua",
  php: "PHP",
  powershell: "PowerShell",
  ruby: "Ruby",
  rust: "Rust",
  swift: "Swift",
  xml: "XML",
  yaml: "YAML",
  plaintext: "sem realce",
};

export function languageLabel(language: string): string {
  return LANGUAGE_LABELS[language] ?? (language || "sem linguagem");
}

/**
 * Chuta a linguagem pelo começo do snippet, para o bloco novo não nascer sem realce.
 *
 * É palpite curto e conservador de propósito: só devolve algo quando o padrão é inequívoco (o
 * `{ "chave":` do JSON, o `def`/`import` do Python, `</` do HTML…). Errou? O seletor ao lado corrige,
 * e a escolha manual nunca é sobrescrita — isto só preenche quando ainda está vazio.
 */
export function guessLanguage(code: string): string | null {
  const text = code.trimStart();
  if (!text) return null;
  const first = text.split("\n", 1)[0] ?? "";
  if (/^[{[]/.test(text) && /"\s*:/.test(text)) return "json";
  if (/^<(!doctype|html|div|span|p|head|body|section|a\s)/i.test(text) || /<\/\w+>/.test(text)) {
    return "html";
  }
  if (/^(def |class |import |from \w+ import|@\w+)/.test(text)) return "python";
  if (/^(SELECT|INSERT INTO|UPDATE|DELETE FROM|CREATE TABLE)\b/i.test(text)) return "sql";
  if (/^(# |## |- |\* |\d+\. )/.test(text)) return "markdown";
  if (/^(function |const |let |var |import .* from|export |console\.log)/.test(text)) return "javascript";
  if (/^\s*[.#]?[\w-]+\s*\{[^}]*:[^}]*;/.test(first + text)) return "css";
  if (/^(\$ |#!\/|sudo |npm |yarn |pnpm |git |docker )/.test(text)) return "bash";
  return null;
}
