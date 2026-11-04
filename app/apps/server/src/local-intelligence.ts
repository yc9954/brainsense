import { randomUUID } from "node:crypto";
import type { CopilotKitIntelligence } from "@copilotkit/runtime/v2";

/**
 * In-memory stand-in for CopilotKit Intelligence (threads, locks, memories, annotations).
 * Lets OpenMuse run its full agent loop locally without a hosted platform key. Threads live for
 * the process lifetime; chat history is held by the client, which is all the headless chat needs.
 * Realtime (Rich Threads) stays off: set RICH_THREADS=false alongside this.
 */
type Thread = {
  id: string;
  name: string | null;
  agentId: string;
  createdById: string;
  createdAt: string;
  updatedAt: string;
  lastUpdatedAt: string;
  archived: boolean;
};
type Memory = {
  id: string;
  kind: string;
  scope: string;
  content: string;
  sourceThreadIds: string[];
  invalidatedAt: string | null;
};

export function isPlaceholderIntelligenceKey(key: string | undefined) {
  return !key || /^(dummy|local|placeholder|none|test)/i.test(key.trim());
}

export class LocalIntelligence {
  private threads = new Map<string, Thread>();
  private memories = new Map<string, Memory>();
  private events = new Map<string, unknown[]>();
  private created = new Set<(t: Thread) => void>();
  private updated = new Set<(t: Thread) => void>();
  private deleted = new Set<(p: { threadId: string; userId: string; agentId: string }) => void>();

  private summary(t: Thread) {
    return { ...t };
  }
  private upsert(params: { threadId: string; userId: string; agentId: string; name?: string }) {
    const now = new Date().toISOString();
    const t: Thread = {
      id: params.threadId,
      name: params.name ?? null,
      agentId: params.agentId,
      createdById: params.userId,
      createdAt: now,
      updatedAt: now,
      lastUpdatedAt: now,
      archived: false,
    };
    this.threads.set(t.id, t);
    for (const cb of this.created) cb(this.summary(t));
    return t;
  }

  onThreadCreated(cb: (t: Thread) => void) {
    this.created.add(cb);
    return () => this.created.delete(cb);
  }
  onThreadUpdated(cb: (t: Thread) => void) {
    this.updated.add(cb);
    return () => this.updated.delete(cb);
  }
  onThreadDeleted(cb: (p: { threadId: string; userId: string; agentId: string }) => void) {
    this.deleted.add(cb);
    return () => this.deleted.delete(cb);
  }
  async getInspectorMetadata() {
    return undefined;
  }
  async getRuntimeEntitlements() {
    return {
      status: "ready" as const,
      entitlement: {
        source: "selfHostedDeploymentLicense" as const,
        features: {},
        limits: {},
        planCode: "local",
      },
    };
  }
  async listThreads(params: { userId: string; agentId: string }) {
    const threads = [...this.threads.values()]
      .filter((t) => t.agentId === params.agentId && !t.archived)
      .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
      .map((t) => this.summary(t));
    return { threads, joinCode: "local", joinToken: "local", nextCursor: null };
  }
  async listMemories(_params: { userId: string }) {
    return { memories: [...this.memories.values()] };
  }
  async createMemory(params: {
    userId: string;
    content: string;
    kind?: string;
    scope?: string;
    sourceThreadIds?: string[];
  }) {
    const m: Memory = {
      id: randomUUID(),
      kind: params.kind ?? "user",
      scope: params.scope ?? "user",
      content: params.content,
      sourceThreadIds: params.sourceThreadIds ?? [],
      invalidatedAt: null,
    };
    this.memories.set(m.id, m);
    return { ...m, absorbed: false };
  }
  async updateMemory(params: { userId: string; id: string; content: string; kind?: string }) {
    const m = this.memories.get(params.id);
    if (!m) throw new Error(`memory ${params.id} not found`);
    m.content = params.content;
    if (params.kind) m.kind = params.kind;
    return { ...m };
  }
  async removeMemory(params: { userId: string; id: string }) {
    this.memories.delete(params.id);
  }
  async recallMemories(params: { userId: string; query: string }) {
    const q = params.query.toLowerCase();
    return {
      memories: [...this.memories.values()]
        .filter((m) => m.content.toLowerCase().includes(q))
        .slice(0, 10),
    };
  }
  async updateThread(params: {
    threadId: string;
    userId: string;
    agentId: string;
    updates: { name?: string; [k: string]: unknown };
  }) {
    const t = this.threads.get(params.threadId) ?? this.upsert(params);
    if (typeof params.updates.name === "string") t.name = params.updates.name;
    if (typeof params.updates.archived === "boolean") t.archived = params.updates.archived;
    t.updatedAt = t.lastUpdatedAt = new Date().toISOString();
    for (const cb of this.updated) cb(this.summary(t));
    return this.summary(t);
  }
  async createThread(params: { threadId: string; userId: string; agentId: string; name?: string }) {
    return this.summary(this.upsert(params));
  }
  async getThread(params: { threadId: string; userId: string }) {
    const t = this.threads.get(params.threadId);
    if (!t) throw new Error(`thread ${params.threadId} not found`);
    return this.summary(t);
  }
  async getOrCreateThread(params: {
    threadId: string;
    userId: string;
    agentId: string;
    name?: string;
  }) {
    const existing = this.threads.get(params.threadId);
    if (existing) return { thread: this.summary(existing), created: false };
    return { thread: this.summary(this.upsert(params)), created: true };
  }
  async getThreadMessages(_params: { threadId: string; userId: string }) {
    return { messages: [] as unknown[] };
  }
  async ɵgetManagedChannelAsset(
    _assetId: string,
  ): Promise<{ bytes: Uint8Array; mimeType?: string }> {
    throw new Error("managed channel assets are not available locally");
  }
  async getThreadEvents(params: { threadId: string }) {
    return {
      events: (this.events.get(params.threadId) ?? []) as { type: string }[],
      decodeErrorRowIds: [],
      truncated: false,
    };
  }
  async getThreadState(_params: { threadId: string }) {
    return { kind: "no-snapshot" as const };
  }
  async archiveThread(params: { threadId: string; userId: string; agentId: string }) {
    const t = this.threads.get(params.threadId);
    if (t) {
      t.archived = true;
      for (const cb of this.updated) cb(this.summary(t));
    }
  }
  async deleteThread(params: { threadId: string; userId: string; agentId: string }) {
    this.threads.delete(params.threadId);
    for (const cb of this.deleted) cb(params);
  }
  async annotate(params: { userId: string; threadId: string; type: string; payload?: unknown }) {
    const list = this.events.get(params.threadId) ?? [];
    list.push({ type: params.type, payload: params.payload, at: new Date().toISOString() });
    this.events.set(params.threadId, list);
    return { id: randomUUID(), duplicate: false };
  }
  async ɵacquireThreadLock(params: {
    threadId: string;
    runId: string;
    userId: string;
    agentId: string;
    ttlSeconds?: number;
  }) {
    if (!this.threads.has(params.threadId)) this.upsert(params);
    return {
      threadId: params.threadId,
      runId: params.runId,
      joinToken: "local",
      lock: { key: `lock:${params.threadId}`, ttlSeconds: params.ttlSeconds ?? 60 },
    };
  }
  async ɵcleanupThreadLock(_params: { threadId: string; runId: string }) {}
  async ɵrenewThreadLock(params: { threadId: string; runId: string; ttlSeconds: number }) {
    return { ttlSeconds: params.ttlSeconds };
  }
  async ɵgetActiveJoinCode(params: { threadId: string; userId: string }) {
    return { threadId: params.threadId, joinToken: "local" };
  }
  async ɵconnectThread(_params: { threadId: string; userId: string; agentId: string }) {
    return null;
  }
  async ɵsubscribeToThreads(_params: { userId: string }) {
    return { joinToken: "local" };
  }
  async ɵsubscribeToMemories(_params: { userId: string }) {
    return { joinToken: "local" };
  }
  ɵgetApiKey() {
    return "local";
  }
  ɵgetApiUrl() {
    return "http://127.0.0.1:1";
  }
  ɵgetChannelsWsUrl() {
    return "ws://127.0.0.1:1";
  }
  ɵgetClientWsUrl() {
    return "ws://127.0.0.1:1";
  }
  ɵgetRunnerWsUrl() {
    return "ws://127.0.0.1:1";
  }
  ɵgetRunnerAuthToken() {
    return "local";
  }
}

export function isLocalIntelligence(x: unknown): boolean {
  return x instanceof LocalIntelligence;
}

export function makeIntelligence(
  apiKey: string,
  real: () => CopilotKitIntelligence,
): CopilotKitIntelligence {
  if (!isPlaceholderIntelligenceKey(apiKey)) return real();
  console.log(
    "[OpenMuse] CPK_INTELLIGENCE_API_KEY is a placeholder → using the local in-memory Intelligence stub",
  );
  return new LocalIntelligence() as unknown as CopilotKitIntelligence;
}
