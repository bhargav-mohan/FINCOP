import type { ReactNode } from "react";

import "./globals.css";

export const metadata = {
  title: "Settlement review",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        <div className="mx-auto max-w-6xl space-y-6 px-4 py-8">{children}</div>
      </body>
    </html>
  );
}
