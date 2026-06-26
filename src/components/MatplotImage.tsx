import React, { useEffect, useState } from "react";

type Props = {
  url: string;          // endpoint
  payload: any;         // POST body
  alt: string;
  className?: string;
};

export default function MatplotImage({ url, payload, alt, className }: Props) {
  const [src, setSrc] = useState<string>("");

  useEffect(() => {
    let abort = false;
    async function run() {
      try {
        const res = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const blob = await res.blob();
        if (!abort) setSrc(URL.createObjectURL(blob));
      } catch {
        if (!abort) setSrc("");
      }
    }
    run();
    return () => { abort = true; };
  }, [url, JSON.stringify(payload)]); // stringify to re-run on deep change

  if (!src) return <div className="text-sm text-gray-500">Plot unavailable.</div>;
  return <img src={src} alt={alt} className={className ?? "w-full h-auto rounded"} />;
}
