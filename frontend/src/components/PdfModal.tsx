import { ArrowSquareOut, FilePdf, X } from "@phosphor-icons/react";
import { useEffect } from "react";

export interface PdfPreview {
  url: string;
  title: string;
}

/**
 * O PDF por cima da tela, lido ali mesmo.
 *
 * Quem desenha continua sendo o visualizador do navegador — `<img>` não desenha PDF e `<object>` está
 * fora do CSP —, agora dentro do `iframe` em vez da aba nova: página, zoom, busca e impressão seguem
 * no topo dele. É para isto que o `/media/<arquivo>` responde `inline`.
 *
 * PDF de outro site só aparece aqui se o dono deixar ser emoldurado (`X-Frame-Options`/`frame-src`);
 * quando não deixa, o botão **Abrir em nova aba** é o caminho.
 */
export function PdfModal({ pdf, onClose }: { pdf: PdfPreview; onClose: () => void }) {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <div
      className="overlay is-centered"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        className="sheet pdf-sheet"
        role="dialog"
        aria-modal="true"
        aria-label={`PDF ${pdf.title}`}
      >
        <div className="sheet-head">
          <p className="confirm-title" title={pdf.title}>
            <FilePdf size={16} weight="bold" />
            {pdf.title}
          </p>
          <span className="pdf-actions">
            <a
              className="btn btn-ghost btn-compact"
              href={pdf.url}
              target="_blank"
              rel="noreferrer"
              title="Abrir o PDF em nova aba"
            >
              <ArrowSquareOut size={14} />
              Abrir em nova aba
            </a>
            <button
              type="button"
              className="icon-btn is-tiny"
              onClick={onClose}
              title="Fechar (Esc)"
              aria-label="Fechar o PDF"
            >
              <X size={14} weight="bold" />
            </button>
          </span>
        </div>

        <iframe className="pdf-frame" src={pdf.url} title={pdf.title} />

        <p className="panel-hint">
          O leitor é o do navegador: página, zoom, busca e impressão ficam no topo dele. Se o arquivo
          não aparecer, o site dele recusa abrir dentro de outra página — use <strong>Abrir em nova
          aba</strong>.
        </p>
      </div>
    </div>
  );
}
