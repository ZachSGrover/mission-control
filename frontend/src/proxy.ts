import { NextResponse } from "next/server";

// Middleware: all routes pass through unconditionally.
// Clerk auth is handled client-side only (required for Electron desktop environment).
export default function middleware() {
  return NextResponse.next();
}

export const config = {
  matcher: [
    "/((?!_next|_clerk|v1|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/(api|trpc)(.*)",
  ],
};
