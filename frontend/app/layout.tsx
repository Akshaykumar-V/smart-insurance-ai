import type { Metadata } from "next";
import "./globals.css";
import "./upload.css";
import "./policy.css";
import "./simulator.css";
import "./auth.css";
export const metadata: Metadata = { title: "Coverly | Insurance Wallet", description: "A fictional insurance wallet. Smart Insurance Wallet hackathon proof-of-concept." };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) { return <html lang="en"><body>{children}</body></html>; }
