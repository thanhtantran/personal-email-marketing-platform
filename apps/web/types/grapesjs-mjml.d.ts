/**
 * `grapesjs-mjml` does not ship type declarations. It exports the MJML plugin
 * as its default export, which GrapesJS accepts via the `plugins` option.
 */
declare module "grapesjs-mjml" {
  import type { Plugin } from "grapesjs";

  const plugin: Plugin;
  export default plugin;
}
