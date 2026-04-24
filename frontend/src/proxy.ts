import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";
import { NextResponse, type NextRequest } from "next/server";

import { isLikelyValidClerkPublishableKey } from "@/auth/clerkKey";

// Routes that must remain reachable without a session.
// Everything else requires authentication when Clerk is the active auth mode.
const isPublicRoute = createRouteMatcher([
  "/sign-in(.*)",
  "/sign-up(.*)",
  "/invite(.*)",
  "/api/webhooks(.*)",
]);

// Only enforce Clerk protection when Clerk is actually the active auth mode
// AND a valid publishable key is configured. In local-auth deployments (e.g.
// the Electron desktop target) or secretless CI builds, the proxy falls
// through unchanged — preserving prior behavior for those environments.
const authMode = process.env.NEXT_PUBLIC_AUTH_MODE;
const clerkActive =
  authMode !== "local" &&
  isLikelyValidClerkPublishableKey(
    process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY,
  );

const passthrough = (_req: NextRequest) => NextResponse.next();

export default clerkActive
  ? clerkMiddleware(async (auth, req) => {
      if (!isPublicRoute(req)) {
        await auth.protect();
      }
    })
  : passthrough;

export const config = {
  matcher: [
    "/((?!_next|_clerk|v1|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/(api|trpc)(.*)",
  ],
};
