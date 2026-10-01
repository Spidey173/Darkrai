import './globals.css';
import { Inter, Syne } from 'next/font/google';

const inter = Inter({
  subsets: ['latin'],
  weight: ['300', '400', '500', '600', '700'],
  variable: '--font-inter',
  display: 'swap',
});

const syne = Syne({
  subsets: ['latin'],
  weight: ['500', '600', '700', '800'],
  variable: '--font-syne',
  display: 'swap',
});

export const metadata = {
  title: 'Darkrai — GitHub Automation',
  description: 'Automate GitHub repositories with event-driven webhooks, smart rule engines, and instant actions.',
  keywords: 'github automation, webhooks, rule engine, devtools',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${inter.variable} ${syne.variable}`}>
      <body>{children}</body>
    </html>
  );
}
