import { useCallback, useEffect, useSyncExternalStore } from "react";
import { ApiError } from "@/lib/errors";

/**
 * A very small data loader for the public pages (check-in, pass, visit status, host
 * response). These pages are the visitor's first load on a phone, often on 3G, so they
 * don't pull in React Query (~17 KB gz): this covers what they need. Same key = shared
 * data (the pass page and its card), deduplicated requests, optional polling, and
 * ``setLoaded`` to put fresh data in after a POST or a live event.
 */

interface Entry<T> {
  data?: T;
  error?: unknown;
  fetching: boolean;
  promise?: Promise<void>;
  listeners: Set<() => void>;
  snapshot: Snapshot<T>;
}
interface Snapshot<T> { data?: T; error?: unknown; fetching: boolean }

const cache = new Map<string, Entry<unknown>>();

function entry<T>(key: string): Entry<T> {
  let e = cache.get(key) as Entry<T> | undefined;
  if (!e) {
    e = { fetching: false, listeners: new Set(), snapshot: { fetching: false } };
    cache.set(key, e as Entry<unknown>);
  }
  return e;
}

function update<T>(key: string, patch: Partial<Snapshot<T>>) {
  const e = entry<T>(key);
  Object.assign(e, patch);
  e.snapshot = { data: e.data, error: e.error, fetching: e.fetching };
  e.listeners.forEach((l) => l());
}

/** Network problems and server errors are worth one more try; a 4xx answer is final. */
const retryable = (e: unknown) => !(e instanceof ApiError) || e.status === 0 || e.status >= 500;

function load<T>(key: string, fn: () => Promise<T>, retry: number): Promise<void> {
  const e = entry<T>(key);
  if (e.promise) return e.promise;
  update<T>(key, { fetching: true });
  e.promise = (async () => {
    let err: unknown;
    for (let i = 0; i <= retry; i++) {
      try {
        update<T>(key, { data: await fn(), error: undefined });
        err = undefined;
        break;
      } catch (x) {
        err = x;
        if (!retryable(x)) break;
      }
    }
    if (err !== undefined) update<T>(key, { error: err });
  })().finally(() => {
    e.promise = undefined;
    update<T>(key, { fetching: false });
  });
  return e.promise;
}

/** Replace the data for a key (after a POST, or from a live event). */
export function setLoaded<T>(key: string, data: T) {
  update<T>(key, { data, error: undefined });
}

export interface Loaded<T> {
  data: T | undefined;
  error: unknown;
  /** First load in progress (nothing to show yet). */
  isLoading: boolean;
  isFetching: boolean;
  refetch: () => Promise<void>;
}

export function useLoad<T>(
  key: string,
  fn: () => Promise<T>,
  opts: { enabled?: boolean; retry?: number; refetchInterval?: number | ((data: T | undefined) => number | false) } = {},
): Loaded<T> {
  const { enabled = true, retry = 1, refetchInterval } = opts;
  const e = entry<T>(key);
  const snap = useSyncExternalStore(
    useCallback((cb) => {
      e.listeners.add(cb);
      return () => e.listeners.delete(cb);
    }, [e]),
    () => e.snapshot,
  );
  // fn changes every render; the key is what identifies the request.
  const refetch = useCallback(() => load(key, fn, retry), [key, retry]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (enabled && snap.data === undefined && snap.error === undefined) void refetch();
  }, [enabled, key]); // eslint-disable-line react-hooks/exhaustive-deps

  const every = typeof refetchInterval === "function" ? refetchInterval(snap.data) : refetchInterval;
  useEffect(() => {
    if (!enabled || !every) return;
    const id = setInterval(() => void refetch(), every);
    return () => clearInterval(id);
  }, [enabled, every, refetch]);

  return {
    data: snap.data,
    error: snap.error,
    isLoading: enabled && snap.data === undefined && snap.error === undefined,
    isFetching: snap.fetching,
    refetch,
  };
}
