import type { PropsWithChildren, ReactNode } from "react";

export function Shell({ title, subtitle, children }: PropsWithChildren<{ title: string; subtitle: string }>) {
  return (
    <div className="shell">
      <div className="bg-grid" />
      <header>
        <p className="eyebrow">PR Review Bot</p>
        <h1>{title}</h1>
        <p className="subtitle">{subtitle}</p>
      </header>
      {children}
    </div>
  );
}

export function Panel({ title, action, children }: PropsWithChildren<{ title: string; action?: ReactNode }>) {
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}
