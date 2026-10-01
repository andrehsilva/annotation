import hljs from "highlight.js/lib/core";
import bash from "highlight.js/lib/languages/bash";
import c from "highlight.js/lib/languages/c";
import cpp from "highlight.js/lib/languages/cpp";
import csharp from "highlight.js/lib/languages/csharp";
import css from "highlight.js/lib/languages/css";
import diff from "highlight.js/lib/languages/diff";
import dockerfile from "highlight.js/lib/languages/dockerfile";
import go from "highlight.js/lib/languages/go";
import ini from "highlight.js/lib/languages/ini";
import java from "highlight.js/lib/languages/java";
import javascript from "highlight.js/lib/languages/javascript";
import json from "highlight.js/lib/languages/json";
import kotlin from "highlight.js/lib/languages/kotlin";
import lua from "highlight.js/lib/languages/lua";
import markdown from "highlight.js/lib/languages/markdown";
import php from "highlight.js/lib/languages/php";
import plaintext from "highlight.js/lib/languages/plaintext";
import powershell from "highlight.js/lib/languages/powershell";
import python from "highlight.js/lib/languages/python";
import ruby from "highlight.js/lib/languages/ruby";
import rust from "highlight.js/lib/languages/rust";
import sql from "highlight.js/lib/languages/sql";
import swift from "highlight.js/lib/languages/swift";
import typescript from "highlight.js/lib/languages/typescript";
import xml from "highlight.js/lib/languages/xml";
import yaml from "highlight.js/lib/languages/yaml";

/**
 * O realce do bloco de código, com o **core** do highlight.js e só as linguagens que o app oferece.
 *
 * Importar `highlight.js` inteiro custaria ~1 MB de bundle; assim são ~40 KB (gzip) pelas linguagens
 * que aparecem no seletor. Nada de CDN nem `eval`: o HTML sai daqui já escapado pelo próprio
 * highlight.js e as cores são classes CSS nossas, que acompanham o tema claro/escuro.
 */
const REGISTERED: Record<string, Parameters<typeof hljs.registerLanguage>[1]> = {
  bash,
  c,
  cpp,
  csharp,
  css,
  diff,
  dockerfile,
  go,
  ini,
  java,
  javascript,
  json,
  kotlin,
  lua,
  markdown,
  php,
  plaintext,
  powershell,
  python,
  ruby,
  rust,
  sql,
  swift,
  typescript,
  xml,
  yaml,
};

for (const [name, language] of Object.entries(REGISTERED)) {
  hljs.registerLanguage(name, language);
}

/** `xml` desenha HTML, mas o seletor chama isso de HTML (e o `html` não existe no highlight.js). */
const ALIASES: Record<string, string> = { html: "xml", shell: "bash", sh: "bash", toml: "ini" };

/**
 * O HTML com a linguagem **adivinhada** — para a prévia da busca, onde não há linguagem declarada.
 *
 * `highlightAuto` roda todas as linguagens registradas sobre o trecho; é caro para um arquivo e
 * barato para os ~140 caracteres de um resultado.
 */
export function highlightAuto(code: string): string {
  try {
    return hljs.highlightAuto(code).value;
  } catch {
    return "";
  }
}

/** O HTML do código realçado — ou `null` quando não há realce para a linguagem escolhida. */
export function highlightCode(code: string, language: string): string | null {
  const id = ALIASES[language] ?? language;
  if (!id || id === "plaintext" || !hljs.getLanguage(id)) return null;
  try {
    return hljs.highlight(code, { language: id, ignoreIllegals: true }).value;
  } catch {
    return null; // realce é enfeite: falhar aqui não pode atrapalhar a escrita
  }
}
