import './globals.css';

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
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

