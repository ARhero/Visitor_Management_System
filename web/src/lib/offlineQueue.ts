/**
 * Guard actions that couldn't reach the server (gate Wi-Fi down, phone in a dead spot).
 *
 * Each action carries its own Idempotency-Key, created when the guard tapped, and the
 * time of the tap. It is retried until the server answers; the key guarantees it is
 * applied at most once however many times it is sent. If the server answers with an
 * error (e.g. someone else already checked the visitor out) the action is dropped and
 * kept in `failed` so the guard can see what didn't go through.
 *
 * Stored in IndexedDB so a reload or a dead battery doesn't lose taps; falls back to
 * memory where IndexedDB isn't available.
 */
import { ApiError } from "./api";

/** "pass-check-in": a pass scanned and checked on the device while offline; the server
 *  repeats the full scan before it counts (see features/guard/offlinePass.ts). */
export type ActionKind = "check-in" | "check-out" | "pass-check-in";

export interface QueuedAction {
  id: string; // also the Idempotency-Key
  visitId: string;
  kind: ActionKind;
  label: string; // visitor name, for the guard's list
  occurredAt: string;
  body: Record<string, unknown>;
  attempts: number;
}

export interface FailedAction extends QueuedAction {
  error: string;
}

export interface Store {
  all(): Promise<QueuedAction[]>;
  put(a: QueuedAction): Promise<void>;
  delete(id: string): Promise<void>;
}

export function memoryStore(): Store {
  const m = new Map<string, QueuedAction>();
  return {
    all: async () => [...m.values()].sort((a, b) => a.occurredAt.localeCompare(b.occurredAt)),
    put: async (a) => void m.set(a.id, a),
    delete: async (id) => void m.delete(id),
  };
}

function idbStore(): Store | null {
  if (typeof indexedDB === "undefined") return null;
  const open = () =>
    new Promise<IDBDatabase>((res, rej) => {
      const r = indexedDB.open("vms-guard", 1);
      r.onupgradeneeded = () => r.result.createObjectStore("outbox", { keyPath: "id" });
      r.onsuccess = () => res(r.result);
      r.onerror = () => rej(r.error);
    });
  const tx = async <T>(mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest<T>) => {
    const db = await open();
    return new Promise<T>((res, rej) => {
      const req = fn(db.transaction("outbox", mode).objectStore("outbox"));
      req.onsuccess = () => res(req.result);
      req.onerror = () => rej(req.error);
    }).finally(() => db.close());
  };
  return {
    all: async () =>
      ((await tx("readonly", (s) => s.getAll())) as QueuedAction[]).sort((a, b) => a.occurredAt.localeCompare(b.occurredAt)),
    put: async (a) => void (await tx("readwrite", (s) => s.put(a))),
    delete: async (id) => void (await tx("readwrite", (s) => s.delete(id))),
  };
}

/** Network trouble (worth retrying) as opposed to the server saying no. */
export function isRetryable(e: unknown): boolean {
  if (e instanceof ApiError) return e.code === "server_unavailable" || e.status === 429 || e.code === "in_progress";
  return true; // fetch threw: offline, DNS, connection reset
}

export type Sender = (a: QueuedAction) => Promise<unknown>;

export class Outbox {
  failed: FailedAction[] = [];
  private listeners = new Set<() => void>();
  private flushing: Promise<void> | null = null;
  private cache: QueuedAction[] = [];

  constructor(
    private store: Store,
    private send: Sender,
  ) {}

  subscribe(fn: () => void) {
    this.listeners.add(fn);
    return () => void this.listeners.delete(fn);
  }
  private emit() {
    for (const fn of this.listeners) fn();
  }

  pending(): QueuedAction[] {
    return this.cache;
  }

  async load() {
    this.cache = await this.store.all();
    this.emit();
  }

  /** Try now; if the network is the problem, keep it for later. Resolves with the
   *  server's answer, or null when queued. Server errors are thrown to the caller. */
  async submit(a: Omit<QueuedAction, "attempts">): Promise<unknown | null> {
    const action = { ...a, attempts: 0 };
    if (typeof navigator !== "undefined" && navigator.onLine === false) {
      await this.keep(action);
      return null;
    }
    try {
      return await this.send(action);
    } catch (e) {
      if (!isRetryable(e)) throw e;
      await this.keep(action);
      return null;
    }
  }

  private async keep(a: QueuedAction) {
    await this.store.put(a);
    await this.load();
  }

  /** Send everything waiting, oldest first. Stops at the first network failure. */
  flush(): Promise<void> {
    this.flushing ??= (async () => {
      try {
        for (const a of await this.store.all()) {
          try {
            await this.send(a);
            await this.store.delete(a.id);
          } catch (e) {
            if (isRetryable(e)) {
              await this.store.put({ ...a, attempts: a.attempts + 1 });
              break;
            }
            await this.store.delete(a.id);
            this.failed = [...this.failed, { ...a, error: e instanceof Error ? e.message : String(e) }];
          }
        }
      } finally {
        await this.load();
        this.flushing = null;
      }
    })();
    return this.flushing;
  }

  dismissFailed() {
    this.failed = [];
    this.emit();
  }
}

export function defaultStore(): Store {
  return idbStore() ?? memoryStore();
}

export function newKey(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}
