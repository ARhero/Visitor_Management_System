import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { CustomField, Department, Org, Page, Purpose, Site, User } from "@/lib/types";

export const keys = {
  org: ["org"] as const,
  sites: ["sites"] as const,
  departments: ["departments"] as const,
  users: (q: object) => ["users", q] as const,
  purposes: ["purposes"] as const,
  fields: ["custom-fields"] as const,
};

export const useOrg = () => useQuery({ queryKey: keys.org, queryFn: () => api<Org>("/org") });
export const useSites = () =>
  useQuery({ queryKey: keys.sites, queryFn: () => api<Site[]>("/sites", { query: { include_inactive: true } }) });
export const useDepartments = () =>
  useQuery({ queryKey: keys.departments, queryFn: () => api<Department[]>("/departments") });
export const usePurposes = () =>
  useQuery({ queryKey: keys.purposes, queryFn: () => api<Purpose[]>("/purposes", { query: { include_inactive: true } }) });
export const useFields = () =>
  useQuery({ queryKey: keys.fields, queryFn: () => api<CustomField[]>("/custom-fields", { query: { include_inactive: true } }) });
export const useUsers = (q: Record<string, unknown>) =>
  useQuery({ queryKey: keys.users(q), queryFn: () => api<Page<User>>("/users", { query: q }), placeholderData: (p) => p });

/** Mutation that invalidates the given query prefixes on success. */
export function useMut<TVars, TOut = unknown>(fn: (v: TVars) => Promise<TOut>, invalidate: readonly (readonly unknown[])[]) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => Promise.all(invalidate.map((k) => qc.invalidateQueries({ queryKey: k }))),
  });
}
