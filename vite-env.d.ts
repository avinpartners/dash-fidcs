/// <reference types="vite/client" />

/** The Metodologia text's anchors, extracted at build time (vite.config.ts). */
declare module "virtual:metodologia-anchors" {
  const anchors: string[];
  export default anchors;
}
