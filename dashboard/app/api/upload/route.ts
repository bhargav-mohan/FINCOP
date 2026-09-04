import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { randomUUID } from "node:crypto";

import { repoRoot } from "@/lib/runFinanceController";

const MAX_FILE_BYTES = 10 * 1024 * 1024;
const MAX_TOTAL_BYTES = 50 * 1024 * 1024;
const MAX_FILES = 40;

const ALLOWED_EXT = new Set([".csv", ".tsv", ".json", ".xlsx", ".xlsm", ".zip"]);

function asFile(value: FormDataEntryValue): File | null {
  if (typeof value === "string") {
    return null;
  }
  if (typeof (value as File).arrayBuffer !== "function") {
    return null;
  }
  return value as File;
}

function collectFiles(form: FormData): File[] {
  const out: File[] = [];
  for (const key of ["files", "zip"]) {
    for (const entry of form.getAll(key)) {
      const file = asFile(entry);
      if (file) {
        out.push(file);
      }
    }
  }
  return out;
}

function relativeName(file: File): string {
  const rel = (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name;
  const parts = rel.split(/[/\\]/).filter((part) => part && part !== "." && part !== "..");
  if (!parts.length) {
    throw new Error("empty");
  }
  return parts.join("/");
}

function extOf(name: string): string {
  const base = name.split("/").pop() ?? name;
  const i = base.lastIndexOf(".");
  return i >= 0 ? base.slice(i).toLowerCase() : "";
}

export async function POST(request: Request) {
  let form: FormData;
  try {
    form = await request.formData();
  } catch {
    return Response.json(
      { error: "Choose CSVs, a folder, an Excel workbook, or a ZIP." },
      { status: 400 }
    );
  }
  try {
    const files = collectFiles(form);
    if (!files.length) {
      return Response.json(
        { error: "Choose CSVs, a folder, an Excel workbook, or a ZIP." },
        { status: 400 }
      );
    }
    if (files.length > MAX_FILES) {
      return Response.json({ error: `Upload at most ${MAX_FILES} files.` }, { status: 400 });
    }

    type Saved = { rel: string; buf: Buffer };
    const saved: Saved[] = [];
    let total = 0;
    for (const file of files) {
      let rel: string;
      try {
        rel = relativeName(file);
      } catch {
        continue;
      }
      const ext = extOf(rel);
      const base = rel.split("/").pop() ?? rel;
      if (base.startsWith(".") || !ALLOWED_EXT.has(ext)) {
        continue;
      }
      const buf = Buffer.from(await file.arrayBuffer());
      if (buf.length === 0) {
        return Response.json({ error: `${rel} is empty.` }, { status: 400 });
      }
      if (buf.length > MAX_FILE_BYTES) {
        return Response.json({ error: `${rel} is larger than 10 MB.` }, { status: 413 });
      }
      total += buf.length;
      if (total > MAX_TOTAL_BYTES) {
        return Response.json({ error: "Upload is larger than 50 MB." }, { status: 413 });
      }
      saved.push({ rel, buf });
    }
    if (!saved.length) {
      return Response.json({ error: "Choose CSVs, a folder, an Excel workbook, or a ZIP." }, { status: 400 });
    }

    const uploadId = randomUUID();
    const dir = path.join(repoRoot(), "dashboard", ".uploads", uploadId);
    await mkdir(dir, { recursive: true });
    const used = new Set<string>();
    for (const item of saved) {
      let unique = item.rel;
      let n = 0;
      while (used.has(unique)) {
        n += 1;
        const ext = path.extname(item.rel);
        const stem = item.rel.slice(0, item.rel.length - ext.length);
        unique = `${stem}_${n}${ext}`;
      }
      used.add(unique);
      const target = path.join(dir, unique);
      const resolved = path.resolve(target);
      if (!resolved.startsWith(path.resolve(dir) + path.sep) && resolved !== path.resolve(dir)) {
        return Response.json({ error: "Invalid file path in upload." }, { status: 400 });
      }
      await mkdir(path.dirname(target), { recursive: true });
      await writeFile(target, item.buf);
    }
    return Response.json({ ok: true, uploadId });
  } catch {
    return Response.json({ error: "Upload failed. Try again." }, { status: 500 });
  }
}
