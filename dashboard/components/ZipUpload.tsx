"use client";

import { useState } from "react";

const ACCEPT =
  ".csv,.tsv,.json,.xlsx,.xlsm,.zip,text/csv,application/json,application/zip,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

function mergeFiles(current: File[], incoming: FileList | File[]): File[] {
  const next = [...current];
  const seen = new Set(
    current.map((f) => `${(f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name}:${f.size}`)
  );
  for (const file of Array.from(incoming)) {
    const key = `${(file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name}:${file.size}`;
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    next.push(file);
  }
  return next;
}

function labelFor(files: File[]): string {
  if (!files.length) {
    return "";
  }
  if (files.length === 1) {
    return files[0].name;
  }
  return `${files.length} files selected`;
}

export function ZipUpload() {
  const [files, setFiles] = useState<File[]>([]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [dragOver, setDragOver] = useState(false);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!files.length) {
      setError("Choose files or a folder first.");
      return;
    }
    const data = new FormData();
    for (const file of files) {
      data.append("files", file);
    }
    setPending(true);
    setError("");
    try {
      const res = await fetch("/api/upload", { method: "POST", body: data });
      const payload = (await res.json().catch(() => ({}))) as {
        error?: string;
        uploadId?: string;
      };
      if (!res.ok || !payload.uploadId) {
        setError(payload.error || "Upload failed. Try CSV, Excel, a folder, or a ZIP.");
        setPending(false);
        return;
      }
      const next = new URLSearchParams();
      next.set("source", "zip");
      next.set("uploadId", payload.uploadId);
      window.location.assign(`/?${next.toString()}`);
    } catch {
      setError("Upload failed. Try again.");
      setPending(false);
    }
  }

  return (
    <form
      onSubmit={onSubmit}
      className="space-y-3 rounded-lg border border-slate-200 bg-white p-4"
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragOver(false);
        if (e.dataTransfer.files?.length) {
          setFiles((prev) => mergeFiles(prev, e.dataTransfer.files));
          setError("");
        }
      }}
    >
      <p className="text-sm text-slate-500">
        Payments, settlements, and bank can be three separate CSVs. Select all of them in one
        upload (hold Cmd/Ctrl to pick multiple), or choose the folder that contains them.
      </p>
      <div
        className={`flex flex-wrap items-end gap-3 rounded-md border border-dashed p-3 ${
          dragOver ? "border-slate-500 bg-slate-50" : "border-slate-200"
        }`}
      >
        <label className="flex flex-col text-sm">
          <span className="mb-1 text-slate-500">Files</span>
          <input
            className="text-sm"
            type="file"
            accept={ACCEPT}
            multiple
            onChange={(e) => {
              if (e.target.files?.length) {
                setFiles((prev) => mergeFiles(prev, e.target.files as FileList));
                setError("");
              }
            }}
          />
        </label>
        <label className="flex flex-col text-sm">
          <span className="mb-1 text-slate-500">Folder</span>
          <input
            className="text-sm"
            type="file"
            multiple
            {...({ webkitdirectory: "", directory: "" } as React.InputHTMLAttributes<HTMLInputElement>)}
            onChange={(e) => {
              if (e.target.files?.length) {
                setFiles((prev) => mergeFiles(prev, e.target.files as FileList));
                setError("");
              }
            }}
          />
        </label>
        <button
          type="submit"
          disabled={pending}
          className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
        >
          {pending ? "Uploading..." : "Upload"}
        </button>
      </div>
      {files.length ? (
        <div className="text-xs text-slate-500">
          <p>
            {labelFor(files)}
            <button type="button" className="ml-2 underline" onClick={() => setFiles([])}>
              Clear
            </button>
          </p>
          <ul className="mt-1 list-inside list-disc">
            {files.map((file) => (
              <li key={`${(file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name}:${file.size}`}>
                {(file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name}
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="text-xs text-slate-400">Or drop the three files here.</p>
      )}
      {error ? <p className="text-sm text-red-600">{error}</p> : null}
    </form>
  );
}
