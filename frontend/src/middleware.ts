import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";
import { NextResponse, type NextRequest } from "next/server";

import { isLikelyValidClerkPublishableKey } from "@/auth/clerkKey";

// Routes that must remain reachable without a session.
// Everything else requires authentication.
const isPublicRoute = createRouteMatcher([
  "/sign-in(.*)",
  "/sign-up(.*)",
  "/invite(.*)",
  "/api/webhooks(.*)",
]);

// Only enforce Clerk protection when Clerk is actually the active auth mode
// AND a valid publishable key is configured. In local-mode deployments or
// secretless CI builds, fall through to Next without touching the request.
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
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|avif|css|js|woff2?|ttf|eot|otf|ico|webmanifest|map|txt|xml)).*)",
  ],
};
