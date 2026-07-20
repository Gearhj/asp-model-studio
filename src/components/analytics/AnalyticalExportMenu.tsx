import { Download } from "lucide-react";
import type { AnalyticalResult } from "../../types/analyticsEngine";

export function AnalyticalExportMenu({ result }: { result: AnalyticalResult }) { const download=()=>{const blob=new Blob([JSON.stringify(result,null,2)],{type:"application/json"});const url=URL.createObjectURL(blob);const anchor=document.createElement("a");anchor.href=url;anchor.download=`atlas-${result.analysis_type}.json`;anchor.click();URL.revokeObjectURL(url);}; return <button type="button" onClick={download} className="atlas-secondary-button inline-flex items-center gap-2"><Download size={14}/>Export analysis JSON</button>; }
