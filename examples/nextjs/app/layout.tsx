import type { Metadata } from 'next';
import type { ReactNode } from 'react';

import './globals.css';

/**
 * The root layout is a server component, which is the point: the token never
 * reaches the client bundle because no client component ever imports
 * `bookroom-sdk/next`.
 */
export const metadata: Metadata = {
  title: 'Bookroom study guide',
  description: 'Generate a study guide from a book through the Bookroom facade.',
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}