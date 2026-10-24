import {
  createCipheriv,
  createDecipheriv,
  randomBytes,
  randomUUID,
} from "node:crypto";

export type Envelope = {
  version: number;
  id: string;
  iv: string;
  data: string;
};
export type RelayQuery = {
  report: string;
  start_date?: string;
  end_date?: string;
  all_time?: boolean;
  refresh?: boolean;
};

function key() {
  const raw = process.env.INSIGHTS_RELAY_KEY ?? "";
  if (!/^[A-Za-z0-9_-]{43}=$/.test(raw))
    throw Error("Relay configuration required");
  return Buffer.from(raw, "base64url");
}
function aad(direction: string, id: string) {
  return Buffer.from(`insights-relay:v1:${direction}:${id}`);
}

export function seal(query: RelayQuery): Envelope {
  const id = randomUUID(),
    iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", key(), iv);
  cipher.setAAD(aad("request", id));
  const plaintext = JSON.stringify({
    issued_at: Math.floor(Date.now() / 1000),
    query,
  });
  const data = Buffer.concat([
    cipher.update(plaintext, "utf8"),
    cipher.final(),
    cipher.getAuthTag(),
  ]);
  return {
    version: 1,
    id,
    iv: iv.toString("base64url"),
    data: data.toString("base64url"),
  };
}

export function open(
  envelope: Envelope,
  requestId: string,
): { status: number; body: unknown } {
  if (
    envelope.version !== 1 ||
    envelope.id !== requestId ||
    !/^[A-Za-z0-9_-]{16}$/.test(envelope.iv) ||
    typeof envelope.data !== "string" ||
    envelope.data.length > 12_000_000 ||
    !/^[A-Za-z0-9_-]+$/.test(envelope.data)
  ) {
    throw Error("Invalid response");
  }
  const data = Buffer.from(envelope.data, "base64url");
  if (data.length < 16) throw Error("Invalid response");
  const cipher = createDecipheriv(
    "aes-256-gcm",
    key(),
    Buffer.from(envelope.iv, "base64url"),
  );
  cipher.setAAD(aad("response", requestId));
  cipher.setAuthTag(data.subarray(-16));
  const result = JSON.parse(
    Buffer.concat([
      cipher.update(data.subarray(0, -16)),
      cipher.final(),
    ]).toString("utf8"),
  );
  if (![200, 400, 503].includes(result.status) || !("body" in result))
    throw Error("Invalid response");
  return result;
}

export async function requestReport(query: RelayQuery) {
  const raw = process.env.INSIGHTS_BACKEND_ORIGIN;
  if (!raw) throw Error("Backend configuration required");
  const origin = new URL(raw);
  if (
    !["http:", "https:"].includes(origin.protocol) ||
    origin.username ||
    origin.password ||
    origin.pathname !== "/" ||
    origin.search ||
    origin.hash
  )
    throw Error("Invalid backend origin");
  const envelope = seal(query);
  const response = await fetch(new URL("/admin/insights/relay", origin), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(envelope),
    cache: "no-store",
    redirect: "error",
    signal: AbortSignal.timeout(65_000),
  });
  if (!response.ok) throw Error("Backend unavailable");
  return open(await response.json(), envelope.id);
}
