import { Code, ImageSquare, LinkSimple, TextT, VideoCamera } from "@phosphor-icons/react";
import type { Icon } from "@phosphor-icons/react";

import type { BlockType } from "./types";

export const KIND_ICONS: Record<BlockType, Icon> = {
  text: TextT,
  code: Code,
  url: LinkSimple,
  image: ImageSquare,
  video: VideoCamera,
};
