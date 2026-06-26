// src/components/TrainingOverlay.tsx
import React from "react";

export default function TrainingOverlay({
  open,
  message = "Training models… This can take a minute.",
}: {
  open: boolean;
  message?: string;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[60] bg-black/40 backdrop-blur-[1px] flex items-center justify-center">
      <div className="bg-white rounded-xl shadow-lg border border-gray-200 p-6 w-[380px] text-center">
        <div className="flex items-center justify-center mb-4">
          <svg
            className="animate-spin h-6 w-6 text-indigo-600 mr-3"
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            viewBox="0 0 24 24"
          >
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"></path>
          </svg>
          <span className="text-sm text-gray-800 font-medium">{message}</span>
        </div>
        <p className="text-xs text-gray-500">Each model card will update as results arrive.</p>
      </div>
    </div>
  );
}
