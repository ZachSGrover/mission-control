// Next.js requires the middleware entry point to be named `middleware.ts`
// at the root of `src/`. All logic lives in `proxy.ts` to keep this file
// as a thin entry point and allow the same logic to be unit-tested.
export { default } from "./proxy";
export { config } from "./proxy";
