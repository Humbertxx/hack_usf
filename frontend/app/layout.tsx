import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import DemoSessionBootstrap from "./components/DemoSessionBootstrap";
import NavBar from "./components/NavBar";
import "./globals.css";
import { OldPeopleProvider } from "./OldPeopleContext";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "ElderWatch",
  description: "ElderWatch, an elderly monitoring platform",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <>
      <html
        lang="en"
        className={`${geistSans.variable} ${geistMono.variable} h-full`}
      >
        <body className="flex min-h-screen flex-col font-sans antialiased">
          <OldPeopleProvider>
            <DemoSessionBootstrap />
            <NavBar />
            {children}
          </OldPeopleProvider>
        </body>
      </html>
    </>
  );
}
