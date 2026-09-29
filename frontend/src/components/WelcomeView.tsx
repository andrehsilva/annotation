import {
  Check,
  CloudArrowUp,
  ImageSquare,
  Keyboard,
  MagnifyingGlass,
  Notebook,
  Sparkle,
  Tag as TagIcon,
  Users,
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
  admin?: boolean;
}

const STEPS: Step[] = [
  {
    key: "estrutura",
    icon: Notebook,
    title: "Caderno, nota, bloco",
    body: (
      <>
        O <strong>caderno</strong> é a pasta, a <strong>nota</strong> é o assunto e o{" "}
        <strong>bloco</strong> é a linha. São seis tipos de bloco — texto, código, url, imagem, vídeo
        e pdf — e o primeiro caderno já nasce com uma nota vazia esperando por você.
      </>
    ),
  },
  {
    key: "escrever",
    icon: Keyboard,
    title: "Escrever sem sair do teclado",
    body: (
      <>
        Na barra do caderno, escreva o nome da nota e dê <Key>Enter</Key>: ela nasce e já abre para
        escrever. Dentro da nota, <Key>/</Key> em um bloco vazio escolhe o tipo (<Key>Ctrl</Key> +
        <Key>Shift</Key> + <Key>L</Key> quando o bloco já tem texto), <Key>Enter</Key> cria o bloco
        seguinte e o <strong>⠿</strong> arrasta para reordenar. Qualquer letra digitada no caderno pula
        para a barra de escrever — e <Key>Esc</Key> fecha paletas e modais.
      </>
    ),
  },
  {
    key: "marcar",
    icon: TagIcon,
    title: "Marcar e ligar",
    body: (
      <>
        <Key>#</Key> abre as tags da nota e do caderno (a tag nova entra nos dois). <Key>[[</Key> ou{" "}
        <Key>@</Key> cita outra nota: além do link, o vínculo aparece em <strong>Relações</strong>, no
        grafo, e na aba <strong>Afinidade</strong> do caderno — é assim que um caderno mostra os
        outros que ele alcança.
      </>
    ),
  },
  {
    key: "achar",
    icon: MagnifyingGlass,
    title: "Achar de novo",
    body: (
      <>
        <Key>Ctrl</Key> + <Key>K</Key> busca em cadernos, notas, blocos e tags. Os contadores no topo
        abrem a lista de um tipo em todos os cadernos, com <strong>Abrir nota</strong> para cair direto
        no bloco. A barra lateral filtra os cadernos pelo nome, pela descrição ou por uma tag.
      </>
    ),
  },
  {
    key: "midia",
    icon: ImageSquare,
    title: "Imagem, vídeo e PDF",
    body: (
      <>
        Cole uma url ou envie o arquivo do disco (até 30 MB). A imagem abre em modal, no tamanho real;
        o vídeo toca ali mesmo; e o PDF abre em modal com o leitor do próprio navegador — página, zoom
        e busca no topo dele. Vídeos do YouTube e do Vimeo entram pelo link.
      </>
    ),
  },
  {
    key: "compartilhar",
    icon: UsersThree,
    title: "Compartilhar com grupos",
    body: (
      <>
        O admin monta os <strong>grupos</strong>; no cabeçalho do caderno, <strong>Compartilhar</strong>{" "}
        dá a um grupo o papel <em>pode escrever</em> ou <em>só pode ler</em>, e quem entrar no grupo
        depois já alcança o caderno. O chip diz com quem cada caderno está compartilhado, e no caderno
        de outra conta cada bloco mostra quem o escreveu.
      </>
    ),
  },
  {
    key: "drive",
    icon: CloudArrowUp,
    title: "Backup no Google Drive",
    body: (
      <>
        O botão do Drive, no topo, conecta a sua conta Google e exporta as notas em Markdown, com a
        mídia. O mesmo botão mostra o último envio e o que ficou pendente.
      </>
    ),
  },
  {
    key: "admin",
    icon: Users,
    title: "Admin",
    admin: true,
    body: (
      <>
        A área <strong>Admin</strong> cria contas e grupos, redefine senhas, ativa e desativa gente, e
        mostra o espaço de mídia de cada um. Quem entra sem conta é o admin quem cria: não existe
        autocadastro.
      </>
    ),
  },
];

/**
 * A introdução do primeiro login, e a mesma tela que o menu do nome reabre em **Como usar**.
 *
 * Quem decide se ela abre é `welcome_seen_at`, na conta: nulo, o login cai aqui; marcado, o app vai
 * direto para os cadernos. Só o botão do fim marca — sair daqui pela barra de cima a deixa para o
 * próximo login.
 */
export function WelcomeView({ user, onDismiss }: { user: User; onDismiss: () => void }) {
  const steps = STEPS.filter((step) => !step.admin || user.role === "admin");
  return (
    <div className="view">
      <header className="kind-head">
        <h1 className="view-title">
          <Sparkle size={20} weight="bold" />
          Boas-vindas, {user.display_name || user.email}
        </h1>
        <p className="view-lede">
          Um caderno de anotações para código. Esta é a leitura do primeiro login: o que o app faz e
          por onde se chega a cada coisa. No fim, o botão decide se ela precisa voltar.
        </p>
      </header>

      <section className="welcome-grid">
        {steps.map((step) => {
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
          A introdução abre no primeiro login. Depois ela fica no menu do seu nome, em{" "}
          <strong>Como usar</strong> — e sair daqui por outro caminho a deixa para o próximo login.
        </p>
      </footer>
    </div>
  );
}
