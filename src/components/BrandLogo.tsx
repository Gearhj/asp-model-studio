import { BRAND } from "../config/brand";
import { Activity } from "lucide-react";

type BrandLogoProps = {
  size?: "sm" | "md" | "lg";
  variant?: "dark" | "light" | "icon";
  showSubtitle?: boolean;
  className?: string;
};

const sizeClasses = {
  sm: { icon: "h-9 w-9", title: "text-[15px]", subtitle: "text-xs" },
  md: { icon: "h-11 w-11", title: "text-xl", subtitle: "text-xs" },
  lg: { icon: "h-14 w-14", title: "text-3xl", subtitle: "text-sm" },
};

export default function BrandLogo({
  size = "md",
  variant = "light",
  showSubtitle = true,
  className = "",
}: BrandLogoProps) {
  const classes = sizeClasses[size];
  return (
    <div className={`flex min-w-0 items-center gap-3 ${className}`}>
      <span
        className={`${classes.icon} relative grid shrink-0 place-items-center overflow-hidden rounded-xl border ${variant === "dark" ? "border-cyan-300/20 bg-cyan-300/10 text-cyan-200" : "border-teal-200 bg-gradient-to-br from-slate-950 to-teal-800 text-cyan-200"}`}
        aria-hidden="true"
      >
        <span className="absolute inset-[22%] rotate-45 rounded-[3px] border border-current opacity-50" />
        <Activity className="relative z-10 h-[48%] w-[48%]" strokeWidth={2.2} />
      </span>
      {variant !== "icon" && (
        <span className="min-w-0">
          <span className={`${classes.title} block whitespace-nowrap font-semibold leading-tight tracking-tight ${variant === "dark" ? "text-white" : "text-slate-950"}`}>
            {BRAND.productName}
          </span>
          {showSubtitle && (
            <span className={`${classes.subtitle} mt-0.5 block whitespace-normal font-medium leading-4 ${variant === "dark" ? "text-slate-400" : "text-slate-500"}`}>
              {BRAND.productSubtitle}
            </span>
          )}
        </span>
      )}
    </div>
  );
}
