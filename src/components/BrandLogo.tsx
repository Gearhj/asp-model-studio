import { BRAND } from "../config/brand";

type BrandLogoProps = {
  size?: "sm" | "md" | "lg";
  variant?: "dark" | "light" | "icon";
  showSubtitle?: boolean;
  className?: string;
};

const sizeClasses = {
  sm: { image: "h-12", icon: "h-7 w-7", title: "text-sm", subtitle: "text-[10px]", max: "max-w-[150px]" },
  md: { image: "h-14", icon: "h-9 w-9", title: "text-lg", subtitle: "text-xs", max: "max-w-[240px]" },
  lg: { image: "h-20", icon: "h-12 w-12", title: "text-2xl", subtitle: "text-sm", max: "max-w-[360px]" },
};

export default function BrandLogo({
  size = "md",
  variant = "light",
  showSubtitle = true,
  className = "",
}: BrandLogoProps) {
  const classes = sizeClasses[size];
  const logo = variant === "dark" ? BRAND.logoDark : variant === "icon" ? BRAND.icon : BRAND.logoLight;

  if (variant === "icon") {
    return (
      <div className={`flex items-center gap-2 ${className}`}>
        <img src={BRAND.icon} alt={`${BRAND.productName} icon`} className={`${classes.icon} shrink-0 rounded-lg`} />
        <div className="min-w-0">
          <div className={`${classes.title} font-semibold leading-tight text-slate-950`}>{BRAND.productName}</div>
          {showSubtitle && <div className={`${classes.subtitle} truncate font-medium text-slate-500`}>{BRAND.productSubtitle}</div>}
        </div>
      </div>
    );
  }

  return (
    <div className={`flex min-w-0 items-center ${className}`}>
      <img src={logo} alt={`${BRAND.productName} logo`} className={`${classes.image} ${classes.max} shrink-0 object-contain`} />
    </div>
  );
}
