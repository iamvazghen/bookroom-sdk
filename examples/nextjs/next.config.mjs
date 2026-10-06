/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // The facade token is read from BOOKROOM_FACADE_TOKEN at request time. It is
  // deliberately absent from this file and from every NEXT_PUBLIC_ variable.
};

export default nextConfig;