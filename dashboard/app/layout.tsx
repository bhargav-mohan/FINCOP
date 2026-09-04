import type { ReactNode } from "react";

import "./globals.css";

export const metadata = {
  title: "Settlement review",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-black focus:px-3 focus:py-2 focus:text-white"
        >
          Skip to review
        </a>
        <div id="main" className="mx-auto max-w-5xl space-y-8 px-4 py-6 sm:px-6 sm:py-10">
          {children}
        </div>
      </body>
    </html>
  );
}
