import type React from "react";

type AtlasPageHeroProps = {
  eyebrow?: string;
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
  aside?: React.ReactNode;
  dark?: boolean;
};

export default function AtlasPageHero({ eyebrow, title, subtitle, actions, aside, dark = false }: AtlasPageHeroProps) {
  return (
    <section className={`atlas-page-hero ${dark ? "atlas-page-hero-dark text-white" : "bg-white text-slate-950"}`}>
      <div className="grid gap-6 p-6 lg:grid-cols-[minmax(0,1fr)_minmax(280px,0.42fr)] lg:items-center">
        <div>
          {eyebrow && <div className={`text-xs font-semibold uppercase tracking-[0.16em] ${dark ? "text-sky-200" : "text-blue-700"}`}>{eyebrow}</div>}
          <h1 className="mt-2 max-w-4xl text-3xl font-semibold tracking-tight sm:text-4xl">{title}</h1>
          {subtitle && <p className={`mt-3 max-w-3xl text-sm leading-6 ${dark ? "text-blue-100" : "text-slate-600"}`}>{subtitle}</p>}
          {actions && <div className="mt-5 flex flex-wrap gap-2">{actions}</div>}
        </div>
        {aside && <div>{aside}</div>}
      </div>
    </section>
  );
}
