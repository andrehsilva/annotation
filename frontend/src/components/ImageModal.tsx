import { X } from "@phosphor-icons/react";
import { useEffect, useState } from "react";

export interface ImagePreview {
  src: string;
  label?: string;
}

interface ImageModalProps {
  image: ImagePreview;
  onClose: () => void;
}

/**
 * A imagem por cima da tela, no tamanho real: cabe na janela → aparece 1:1; não cabe → encolhe até
 * caber, e um clique devolve o 1:1 com rolagem. As dimensões naturais ficam na legenda.
 */
export function ImageModal({ image, onClose }: ImageModalProps) {
  const [size, setSize] = useState<{ width: number; height: number } | null>(null);
  const [zoomed, setZoomed] = useState(false);
  const [failed, setFailed] = useState(false);

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
      <figure
        className={zoomed ? "image-modal is-zoomed" : "image-modal"}
        role="dialog"
        aria-modal="true"
        aria-label={image.label || "Imagem"}
      >
        <div
          className="image-stage"
          onClick={() => setZoomed((value) => !value)}
          title={zoomed ? "Clique para ajustar à janela" : "Clique para ver em 1:1"}
        >
          {failed ? (
            <p className="panel-hint">Não foi possível carregar {image.src}</p>
          ) : (
            <img
              src={image.src}
              alt={image.label || "imagem da nota"}
              onLoad={(event) =>
                setSize({
                  width: event.currentTarget.naturalWidth,
                  height: event.currentTarget.naturalHeight,
                })
              }
              onError={() => setFailed(true)}
            />
          )}
        </div>
        <figcaption className="image-caption">
          <span className="image-label">{image.label || "imagem"}</span>
          {size && (
            <span className="image-size">
              {size.width}×{size.height}px
            </span>
          )}
          <span className="image-hint">
            {zoomed ? "em 1:1 · clique para ajustar" : "clique na imagem para 1:1 · Esc fecha"}
          </span>
          <button
            type="button"
            className="icon-btn is-tiny"
            onClick={onClose}
            title="Fechar (Esc)"
            aria-label="Fechar imagem"
          >
            <X size={14} />
          </button>
        </figcaption>
      </figure>
    </div>
  );
}
