import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { FilePlus2 } from "lucide-react";
import BrandLogo from "../components/BrandLogo";
import { registerDataset } from "../lib/datasetLibrary";

export default function RegisterDataset() {
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [domain, setDomain] = useState("Consumer Lending");
  const [sourceType, setSourceType] = useState("metadata-only");
  const [message, setMessage] = useState("");

  async function submit() {
    if (!name.trim()) {
      setMessage("Dataset name is required.");
      return;
    }
    try {
      const dataset = await registerDataset({ name, description, domain, sourceType });
      navigate(`/datasets/${dataset.datasetId}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ATLAS could not register this dataset.");
    }
  }

  return (
    <div className="w-full space-y-5">
      <section className="rounded-xl border border-slate-200/80 bg-white/90 p-5 shadow-sm">
        <BrandLogo size="md" variant="light" showSubtitle className="mb-3" />
        <div className="flex items-center gap-2">
          <FilePlus2 size={21} className="text-blue-700" />
          <h1 className="text-xl font-semibold text-slate-950">Register Dataset Metadata</h1>
        </div>
        <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-600">
          Create a metadata-only dataset record for governed sources that are not uploaded through ATLAS yet.
        </p>
      </section>
      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="grid gap-4">
          <label className="grid gap-1 text-sm font-semibold text-slate-700">
            Dataset Name
            <input className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal" value={name} onChange={(event) => setName(event.target.value)} />
          </label>
          <label className="grid gap-1 text-sm font-semibold text-slate-700">
            Description
            <textarea className="min-h-28 rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal" value={description} onChange={(event) => setDescription(event.target.value)} />
          </label>
          <div className="grid gap-4 md:grid-cols-2">
            <label className="grid gap-1 text-sm font-semibold text-slate-700">
              Domain
              <input className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal" value={domain} onChange={(event) => setDomain(event.target.value)} />
            </label>
            <label className="grid gap-1 text-sm font-semibold text-slate-700">
              Source Type
              <select className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal" value={sourceType} onChange={(event) => setSourceType(event.target.value)}>
                <option value="metadata-only">Metadata only</option>
                <option value="sql">SQL database</option>
                <option value="cloud">Cloud/object storage</option>
                <option value="vendor">Vendor extract</option>
                <option value="data-warehouse">Enterprise data warehouse</option>
              </select>
            </label>
          </div>
          {message && <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">{message}</div>}
          <button type="button" onClick={submit} className="w-fit rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-slate-800">
            Register Dataset
          </button>
        </div>
      </section>
    </div>
  );
}

