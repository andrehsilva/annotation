import { ShareNetwork, UsersThree } from "@phosphor-icons/react";

import { SHARE_ROLE_LABELS } from "../lib/format";
import type { NotebookSummary } from "../lib/types";

/** Quantos nomes de grupo cabem no chip antes de virar `+N`; o `title` leva a lista inteira. */
const CHIP_GROUPS = 2;

/**
 * O compartilhamento do caderno nos **dois** sentidos: o que chegou de outra conta e o que saiu desta.
 *
 * O mesmo chip aparece nas três telas que listam cadernos — o caderno aberto, o cartão da lista e a
 * barra lateral (onde ele é só o ícone). Antes ele só existia para quem **recebeu** o caderno: o dono
 * não tinha como saber, olhando a lista, qual dos cadernos dele estava compartilhado.
 */
export function ShareBadge({
  notebook,
  compact = false,
}: {
  notebook: NotebookSummary;
  compact?: boolean;
}) {
  const copy = shareCopy(notebook);
  if (!copy) return null;
  const Icon = copy.inbound ? UsersThree : ShareNetwork;
  if (compact) {
    return (
      <span className="nb-item-shared" title={copy.title}>
        <Icon size={12} weight="bold" />
      </span>
    );
  }
  return (
    <span className="tag-chip is-shared" title={copy.title}>
      <Icon size={11} weight="bold" />
      {copy.text}
    </span>
  );
}

/**
 * A frase do chip. O `text` cabe no cartão e o `title` — o mesmo texto ao passar o mouse — diz a lista
 * inteira de grupos; `null` quando o caderno não é compartilhado em sentido nenhum.
 */
function shareCopy(
  notebook: NotebookSummary,
): { text: string; title: string; inbound: boolean } | null {
  if (notebook.shared) {
    const phrase = `Compartilhado por ${notebook.owner_name || "outra conta"} · ${
      SHARE_ROLE_LABELS[notebook.role]
    }`;
    return { text: phrase, title: phrase, inbound: true };
  }
  const groups = notebook.shared_groups;
  if (groups.length === 0) return null;
  const audience =
    notebook.shared_people === 0
      ? "sem membros ainda"
      : notebook.shared_people === 1
        ? "1 pessoa"
        : `${notebook.shared_people} pessoas`;
  const shown =
    groups.length > CHIP_GROUPS
      ? `${groups.slice(0, CHIP_GROUPS).join(", ")} +${groups.length - CHIP_GROUPS}`
      : groups.join(", ");
  return {
    text: `Compartilhado com ${shown} · ${audience}`,
    title: `Compartilhado com ${groups.join(", ")} · ${audience}`,
    inbound: false,
  };
}
