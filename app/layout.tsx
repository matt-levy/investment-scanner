import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Asymmetry | Research Terminal",
  description: "A research workspace for exploring asymmetric financial opportunities.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="en"><body>{children}</body></html>;
}
