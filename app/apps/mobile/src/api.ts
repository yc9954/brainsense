import Constants from "expo-constants";
import { Platform } from "react-native";
import { readApiPayload } from "./api-response";

/**
 * On a phone in Expo Go the Metro host (Constants.expoConfig.hostUri = "<lan-ip>:8081") tells us
 * where the laptop is; the sample server itself is loopback-only, so we talk to the LAN proxy on
 * :8788 (`node scripts/lan-proxy.mjs`). EXPO_PUBLIC_API_URL still overrides everything.
 */
function lanApiUrl(): string | undefined {
  if (Platform.OS === "web") {
    // the web build opened on a phone over Wi-Fi: talk to the LAN proxy on the same host
    const loc = typeof window !== "undefined" ? window.location : undefined;
    const h = loc?.hostname ?? "";
    if (!h || h === "localhost" || h === "127.0.0.1") return undefined;
    // https://<lan-ip>:8443 (scripts/lan-https.mjs) serves page + API on one origin
    if (loc?.protocol === "https:") return loc.origin;
    return `http://${h}:8788`;
  }
  const host = Constants.expoConfig?.hostUri?.split(":")[0];
  if (!host || host === "localhost" || host === "127.0.0.1") return undefined;
  return `http://${host}:8788`;
}
export const API_URL = (
  process.env.EXPO_PUBLIC_API_URL ||
  lanApiUrl() ||
  (Platform.OS === "android" ? "http://10.0.2.2:8787" : "http://localhost:8787")
).replace(/\/$/, "");

export class MuseApi {
  constructor(readonly token: string) {}
  async request<T>(path: string, body?: unknown, method?: string): Promise<T> {
    const response = await fetch(`${API_URL}${path}`, {
      method: method ?? (body === undefined ? "GET" : "POST"),
      headers: {
        Authorization: `Bearer ${this.token}`,
        ...(body === undefined || body instanceof FormData
          ? {}
          : { "Content-Type": "application/json" }),
      },
      body: body === undefined ? undefined : body instanceof FormData ? body : JSON.stringify(body),
    });
    const payload = await readApiPayload<T>(response);
    return payload;
  }
  url(path: string) {
    return path.startsWith("http") ? path : `${API_URL}${path}`;
  }
}

export async function createSession(
  accessKey?: string,
): Promise<{ token: string; mode: "sample" | "live" }> {
  const response = await fetch(`${API_URL}/api/session`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ accessKey }),
  });
  const payload = await readApiPayload<{ token: string; mode: "sample" | "live" }>(
    response,
    "Could not open your workspace.",
  );
  return payload;
}
