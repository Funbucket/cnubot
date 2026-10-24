import { createCipheriv, createDecipheriv, randomBytes, randomUUID } from "node:crypto";
import type { Envelope } from "./relay";

export type AdminRequest = {
  method: string;
  path: string;
  query: string;
  body: string;
  headers: Record<string, string>;
};
export type AdminResponse = { status: number; content_type: string; body: string };

function key() {
  const raw = process.env.INSIGHTS_RELAY_KEY ?? "";
  if (!/^[A-Za-z0-9_-]{43}=$/.test(raw)) throw Error("Connection configuration required");
  return Buffer.from(raw, "base64url");
}
const aad = (direction: string, id: string) => Buffer.from(`admin-bridge:v1:${direction}:${id}`);

export function sealAdmin(request: AdminRequest): Envelope {
  const username = process.env.INSIGHTS_ADMIN_USERNAME;
  const password = process.env.INSIGHTS_ADMIN_PASSWORD;
  if (!username || !password) throw Error("Administrator configuration required");
  const id = randomUUID(), iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", key(), iv);
  cipher.setAAD(aad("request", id));
  const body = JSON.stringify({ ...request, username, password, issued_at: Math.floor(Date.now() / 1000) });
  const data = Buffer.concat([cipher.update(body, "utf8"), cipher.final(), cipher.getAuthTag()]);
  return { version: 1, id, iv: iv.toString("base64url"), data: data.toString("base64url") };
}

export function openAdmin(envelope: Envelope, requestId: string): AdminResponse {
  if (envelope.version !== 1 || envelope.id !== requestId || typeof envelope.iv !== "string" || !/^[A-Za-z0-9_-]{16}$/.test(envelope.iv) || typeof envelope.data !== "string" || envelope.data.length > 12_000_000 || !/^[A-Za-z0-9_-]+$/.test(envelope.data)) throw Error("Invalid response");
  const bytes = Buffer.from(envelope.data, "base64url");
  if (bytes.length < 16) throw Error("Invalid response");
  const cipher = createDecipheriv("aes-256-gcm", key(), Buffer.from(envelope.iv, "base64url"));
  cipher.setAAD(aad("response", requestId));
  cipher.setAuthTag(bytes.subarray(-16));
  const payload = JSON.parse(Buffer.concat([cipher.update(bytes.subarray(0, -16)), cipher.final()]).toString("utf8"));
  if (!Number.isInteger(payload.status) || !((payload.status >= 200 && payload.status < 300) || (payload.status >= 400 && payload.status < 600)) || typeof payload.body !== "string" || typeof payload.content_type !== "string" || !/^application\/json(; charset=utf-8)?$/i.test(payload.content_type)) throw Error("Invalid response");
  return payload;
}

export async function requestAdmin(request: AdminRequest) {
  const origin = new URL(process.env.INSIGHTS_BACKEND_ORIGIN ?? "");
  if (!["http:", "https:"].includes(origin.protocol) || origin.username || origin.password || origin.pathname !== "/" || origin.search || origin.hash) throw Error("Invalid connection configuration");
  const envelope = sealAdmin(request);
  const response = await fetch(new URL("/admin/workspace/relay", origin), {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(envelope), cache: "no-store", redirect: "error", signal: AbortSignal.timeout(85_000),
  });
  if (!response.ok) throw Error("Administrator connection unavailable");
  return openAdmin(await response.json(), envelope.id);
}
