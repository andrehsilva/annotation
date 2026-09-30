import {
  Check,
  CloudArrowUp,
  Keyboard,
  NoteBlank,
  Sparkle,
  Tag as TagIcon,
  UsersThree,
} from "@phosphor-icons/react";
import type { Icon } from "@phosphor-icons/react";
import type { ReactNode } from "react";

import type { User } from "../lib/types";
import { Key } from "./ui";

/** Um cartão da introdução: ícone, título e o texto que explica aquele pedaço do app. */
interface Step {
  key: string;
  icon: Icon;
  title: string;
  body: ReactNode;
}

const STEPS: Step[] = [
  {
    key: "nota",
    icon: NoteBlank,
    title: "A nota é tudo",
    body: (
      <>
        Cada nota guarda os seus <strong>blocos</strong> — texto, código, url, imagem, vídeo e pdf —,
        as tags e os vínculos. Não há pasta: a lista lateral mostra todas as notas que você alcança, e
        o que você quer é escrever e voltar depois.
      </>
    ),
  },
  {
    key: "escrever",
    icon: Keyboard,
    title: "Escrever sem sair do teclado",
    body: (
      <>
        <Key>/</Key> no bloco vazio escolhe o tipo (<Key>Ctrl</Key>+<Key>Shift</Key>+<Key>L</Key> com
        texto), <Key>Enter</Key> cria o próximo, <Key>⠿</Key> reordena, <Key>Ctrl</Key>+<Key>K</Key>{" "}
        busca em tudo e <Key>Ctrl</Key>+<Key>/</Key> mostra a lista completa de atalhos.
      </>
    ),
  },
  {
    key: "ligar",
    icon: TagIcon,
    title: "Marcar e ligar",
    body: (
      <>
        <Key>#</Key> aplica tags (na nota) e <Key>[[</Key> cita outra nota. O que se cita aparece no
        painel de vínculos da nota e no grafo, em <strong>Relações</strong>.
      </>
    ),
  },
  {
    key: "compartilhar",
    icon: UsersThree,
    title: "Compartilhar uma nota",
    body: (
      <>
        No cabeçalho da nota, <strong>Compartilhar</strong> dá a um grupo o papel{" "}
        <em>pode escrever</em> ou <em>só pode ler</em>. O chip diz com quem a nota está compartilhada,
        e num bloco de outra conta aparece o nome de quem o escreveu.
      </>
    ),
  },
  {
    key: "drive",
    icon: CloudArrowUp,
    title: "Backup e contas",
    body: (
      <>
        O botão do Drive, no menu do seu nome, exporta as notas em Markdown para a sua conta Google.
        Ali também ficam <strong>Atividade</strong>, <strong>Trocar senha</strong> e — para o admin —{" "}
        <strong>Admin</strong>, com contas e grupos.
      </>
    ),
  },
];

/**
 * A introdução do primeiro login, e a mesma tela que o menu do nome reabre em **Como usar**.
 *
 * Quem decide se ela abre é `welcome_seen_at`, na conta: nulo, o login cai aqui; marcado, o app vai
 * direto para a primeira nota. Só o botão do fim marca — sair daqui pela barra de cima a deixa para
 * o próximo login.
 */
export function WelcomeView({ user, onDismiss }: { user: User; onDismiss: () => void }) {
  return (
    <div className="view">
      <header className="kind-head">
        <h1 className="view-title">
          <Sparkle size={20} weight="bold" />
          Boas-vindas, {user.display_name || user.email}
        </h1>
        <p className="view-lede">
          Um caderno de anotações para devs. Em cinco cartões, o que o app faz — e o botão do fim
          decide se esta tela volta.
        </p>
      </header>

      <section className="welcome-grid">
        {STEPS.map((step) => {
          const StepIcon = step.icon;
          return (
            <article className="welcome-card" key={step.key}>
              <p className="welcome-card-head">
                <StepIcon size={16} weight="bold" />
                {step.title}
              </p>
              <p className="welcome-card-body">{step.body}</p>
            </article>
          );
        })}
      </section>

      <footer className="welcome-foot">
        <button type="button" className="btn btn-primary" onClick={onDismiss}>
          <Check size={15} weight="bold" />
          Não mostrar de novo
        </button>
        <p className="panel-hint">
          Ela fica no menu do seu nome, em <strong>Como usar</strong> — e sair daqui por outro caminho
          a deixa para o próximo login.
        </p>
      </footer>
    </div>
  );
}
