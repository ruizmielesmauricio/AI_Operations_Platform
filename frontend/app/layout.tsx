import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI Operations Platform",
  description: "Turning small-business ops data into decisions.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
