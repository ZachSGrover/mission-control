/** @type {import('next').NextConfig} */
const nextConfig = {
  allowedDevOrigins: ["192.168.1.101", "localhost", "127.0.0.1"],
  // Point file tracing to the frontend directory so Next.js doesn't
  // get confused by the parent-level lockfile
  outputFileTracingRoot: __dirname,
  images: {
    remotePatterns: [
      {
        protocol: "https",
        hostname: "img.clerk.com",
      },
    ],
  },
};

module.exports = nextConfig;
