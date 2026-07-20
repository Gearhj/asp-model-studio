import type React from "react";

export type AtlasTabItem = {
  id: string;
  label: string;
  panel: React.ReactNode;
};

type AtlasTabsProps = {
  tabs: AtlasTabItem[];
  activeTab: string;
  onChange: (tabId: string) => void;
  label: string;
};

export default function AtlasTabs({ tabs, activeTab, onChange, label }: AtlasTabsProps) {
  const active = tabs.find((tab) => tab.id === activeTab) ?? tabs[0];
  return (
    <div>
      <div className="flex flex-wrap gap-2 rounded-2xl border border-slate-200 bg-white p-2 shadow-sm" role="tablist" aria-label={label}>
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={active.id === tab.id}
            aria-controls={`${tab.id}-panel`}
            id={`${tab.id}-tab`}
            className={`atlas-tab-button ${active.id === tab.id ? "atlas-tab-button-active" : "atlas-tab-button-inactive"}`}
            onClick={() => onChange(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <div id={`${active.id}-panel`} role="tabpanel" aria-labelledby={`${active.id}-tab`} className="mt-5">
        {active.panel}
      </div>
    </div>
  );
}
