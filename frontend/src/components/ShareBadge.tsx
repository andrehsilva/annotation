import { ShareNetwork, UsersThree } from "@phosphor-icons/react";

import { SHARE_ROLE_LABELS } from "../lib/format";
import type { NoteSummary } from "../lib/types";

/** Quantos nomes de grupo cabem no chip antes de virar `+N`; o `title` leva a lista inteira. */
const CHIP_GROUPS = 2;

/**
 * O compartilhamento da nota nos **dois** sentidos: o que chegou de outra conta e o que saiu desta.
 *
 * O mesmo chip aparece nas duas listas onde uma nota aparece — o cartão da lista principal e a barra
 * lateral (onde ele é só o ícone). Antes ele só existia para quem **recebeu** a nota: o dono não tinha
 * como saber, olhando a lista, qual delas estava compartilhada.
 */
export function ShareBadge({
  note,
  compact = false,
}: {
  note: NoteSummary;
  compact?: boolean;
}) {
  const copy = shareCopy(note);
  if (!copy) return null;
  const Icon = copy.inbound ? UsersThree : ShareNetwork;
  if (compact) {
    return (
      <span className="side-note-shared" title={copy.title}>
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
 * inteira de grupos; `null` quando a nota não é compartilhada em sentido nenhum.
 */
function shareCopy(
  note: NoteSummary,
): { text: string; title: string; inbound: boolean } | null {
  if (note.shared) {
    const phrase = `Compartilhado por ${note.owner_name || "outra conta"} · ${
      SHARE_ROLE_LABELS[note.role]
    }`;
    return { text: phrase, title: phrase, inbound: true };
  }
  const groups = note.shared_groups;
  if (groups.length === 0) return null;
  const audience =
    note.shared_people === 0
      ? "sem membros ainda"
      : note.shared_people === 1
        ? "1 pessoa"
        : `${note.shared_people} pessoas`;
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
