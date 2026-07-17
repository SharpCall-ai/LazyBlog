/**
 * Example LazyBlog receiver — Next.js App Router.
 * Drop at: src/app/api/lazyblog/route.ts, then point site.toml's webhook_url here.
 *
 * Set LAZYBLOG_SECRET to the same value as LAZYBLOG_SECRET_<SITE> in LazyBlog's env.
 *
 * READ THIS BEFORE SHIPPING: writing into the app directory works on a long-lived
 * server and loses every post on platforms with an ephemeral or read-only filesystem
 * (Vercel, most container hosts). Point CONTENT_DIR at a mounted volume, or replace
 * the write with a git commit / S3 put / DB insert. See the README's "Writing a
 * receiver" section.
 */
import { createHmac, timingSafeEqual } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { revalidatePath } from "next/cache";
import { NextResponse } from "next/server";

const CONTENT_DIR = path.join(process.cwd(), "content", "blog");
const SLUG_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

export async function POST(request: Request) {
  const secret = process.env.LAZYBLOG_SECRET;
  if (!secret) {
    console.error("LAZYBLOG_SECRET is not set; refusing every delivery");
    return NextResponse.json({ error: "not configured" }, { status: 500 });
  }

  // The raw body, byte for byte. Signing a re-serialized object would not match.
  const raw = await request.text();
  if (!verify(secret, raw, request.headers.get("x-lazyblog-signature"))) {
    return NextResponse.json({ error: "bad signature" }, { status: 401 });
  }

  const { slug, markdown } = JSON.parse(raw) as { slug: string; markdown: string };
  // A signature proves who sent it, not that the payload is sane. This slug becomes
  // a file path.
  if (!SLUG_RE.test(slug ?? "") || typeof markdown !== "string") {
    return NextResponse.json({ error: "bad payload" }, { status: 400 });
  }

  await mkdir(CONTENT_DIR, { recursive: true });
  await writeFile(path.join(CONTENT_DIR, `${slug}.md`), markdown, "utf-8");

  revalidatePath("/blog");
  revalidatePath(`/blog/${slug}`);

  return NextResponse.json({ ok: true, slug });
}

function verify(secret: string, raw: string, header: string | null): boolean {
  if (!header) return false;
  const expected = `sha256=${createHmac("sha256", secret).update(raw).digest("hex")}`;
  const a = Buffer.from(header);
  const b = Buffer.from(expected);
  // timingSafeEqual throws on a length mismatch, so check that first.
  return a.length === b.length && timingSafeEqual(a, b);
}
