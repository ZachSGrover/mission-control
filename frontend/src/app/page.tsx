// Root redirect is handled in next.config.js → redirects() as an HTTP 307.
// This file intentionally left minimal — Next.js requires a page export
// but the config-level redirect fires before this component ever renders.
export default function Page() {
  return null;
}
