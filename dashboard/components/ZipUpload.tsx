"use client";

import { useRef, useState } from "react";

import { Button } from "@/components/ui/Button";

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
  return `${files.length} files ready`;
}

type UploadPayload = { error?: string; uploadId?: string };

function postFiles(
  files: File[],
  onProgress: (pct: number) => void
): Promise<{ ok: boolean; payload: UploadPayload }> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const data = new FormData();
    for (const file of files) {
      data.append("files", file);
    }
    xhr.open("POST", "/api/upload");
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && event.total > 0) {
        onProgress(Math.min(100, Math.round((event.loaded / event.total) * 100)));
      }
    };
    xhr.onload = () => {
      let payload: UploadPayload = {};
      try {
        payload = JSON.parse(xhr.responseText || "{}") as UploadPayload;
      } catch {
        payload = {};
      }
      resolve({
        ok: xhr.status >= 200 && xhr.status < 300 && Boolean(payload.uploadId),
        payload,
      });
    };
    xhr.onerror = () => reject(new Error("network"));
    xhr.send(data);
  });
}

function buttonLabel(pending: boolean, phase: "idle" | "upload" | "review", progress: number | null): string {
  if (!pending) {
    return "Start review";
  }
  if (phase === "review") {
    return "Matching your files…";
  }
  if (progress != null && progress < 100) {
    return `Uploading ${progress}%`;
  }
  return "Uploading…";
}

export function ZipUpload({ compact = false }: { compact?: boolean }) {
  const [files, setFiles] = useState<File[]>([]);
  const [pending, setPending] = useState(false);
  const [phase, setPhase] = useState<"idle" | "upload" | "review">("idle");
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const folderInput = useRef<HTMLInputElement>(null);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!files.length) {
      setError("Add a ZIP, Excel file, or the CSVs first.");
      return;
    }
    setPending(true);
    setPhase("upload");
    setProgress(0);
    setError("");
    try {
      const { ok, payload } = await postFiles(files, setProgress);
      if (!ok || !payload.uploadId) {
        setError(payload.error || "Could not upload. Try a ZIP, Excel, a folder, or separate CSVs.");
        setPending(false);
        setPhase("idle");
        setProgress(null);
        return;
      }
      setProgress(100);
      setPhase("review");
      const next = new URLSearchParams();
      next.set("source", "zip");
      next.set("uploadId", payload.uploadId);
      next.set("n", String(Date.now()));
      window.location.href = `/?${next.toString()}`;
    } catch {
      setError("Could not upload. Check the connection and try again.");
      setPending(false);
      setPhase("idle");
      setProgress(null);
    }
  }

  return (
    <form
      onSubmit={onSubmit}
      className={compact ? "space-y-3" : "space-y-4"}
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
      {!compact ? (
        <ol className="grid gap-2 text-sm text-muted sm:grid-cols-3">
          <li>
            <span className="font-medium text-ink">1. Drop files</span>
            <span className="block">ZIP, Excel, a folder, or CSVs.</span>
          </li>
          <li>
            <span className="font-medium text-ink">2. We match them</span>
            <span className="block">Payments to settlements to the bank.</span>
          </li>
          <li>
            <span className="font-medium text-ink">3. You finish leftovers</span>
            <span className="block">Only unmatched items land here.</span>
          </li>
        </ol>
      ) : null}

      <input
        ref={fileInput}
        className="sr-only"
        type="file"
        accept={ACCEPT}
        multiple
        disabled={pending}
        onChange={(e) => {
          if (e.target.files?.length) {
            setFiles(Array.from(e.target.files));
            setError("");
          }
          e.target.value = "";
        }}
      />
      <input
        ref={folderInput}
        className="sr-only"
        type="file"
        multiple
        disabled={pending}
        {...({ webkitdirectory: "", directory: "" } as React.InputHTMLAttributes<HTMLInputElement>)}
        onChange={(e) => {
          if (e.target.files?.length) {
            setFiles(Array.from(e.target.files));
            setError("");
          }
          e.target.value = "";
        }}
      />

      <div
        className={`rounded-uber border-2 border-dashed bg-white px-4 py-8 text-center sm:px-8 ${
          dragOver ? "border-ink bg-wash" : "border-line"
        }`}
      >
        <p className="text-base font-medium text-ink">Drop payments, settlements, and the bank file</p>
        <p className="mt-1 text-sm text-muted">
          One ZIP or Excel workbook is enough. Separate CSVs work too. We detect encoding and delimiters.
        </p>
        <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
          <Button type="button" disabled={pending} onClick={() => fileInput.current?.click()}>
            Choose files
          </Button>
          <Button type="button" variant="secondary" disabled={pending} onClick={() => folderInput.current?.click()}>
            Choose folder
          </Button>
        </div>
      </div>

      {files.length ? (
        <div className="rounded-uber border border-line bg-white px-4 py-3 text-sm">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="font-medium text-ink">{labelFor(files)}</p>
            {!pending ? (
              <Button variant="ghost" onClick={() => setFiles([])}>
                Clear
              </Button>
            ) : null}
          </div>
          <ul className="mt-2 max-h-32 overflow-auto text-sm text-muted">
            {files.slice(0, 8).map((file) => (
              <li key={`${(file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name}:${file.size}`}>
                {(file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name}
              </li>
            ))}
            {files.length > 8 ? <li>+{files.length - 8} more</li> : null}
          </ul>
        </div>
      ) : null}

      {pending && progress != null ? (
        <div
          className="h-1.5 overflow-hidden rounded-full bg-line"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={progress}
          aria-label="Upload progress"
        >
          <div className="h-full bg-ink" style={{ width: `${progress}%` }} />
        </div>
      ) : null}

      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={pending || !files.length}>
          {buttonLabel(pending, phase, progress)}
        </Button>
        <p className="text-sm text-muted" aria-live="polite">
          {pending
            ? phase === "review"
              ? "Uploaded. Matching now — this can take a minute."
              : "Sending files…"
            : files.length
              ? "Ready when you are."
              : "Nothing uploaded yet."}
        </p>
      </div>
      {error ? (
        <p className="text-sm text-red-700" role="alert">
          {error}
        </p>
      ) : null}
    </form>
  );
}
