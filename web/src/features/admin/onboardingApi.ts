import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export interface ChecklistStep { key: string; label: string; detail: string; done: boolean; wizard: boolean }
export interface Checklist {
  steps: ChecklistStep[];
  done: number;
  total: number;
  complete: boolean;
  dismissed: boolean;
  test_visit: { id: string; status: string; requested_at: string } | null;
}

export const useChecklist = (poll = false) =>
  useQuery({
    queryKey: ["onboarding"],
    queryFn: () => api<Checklist>("/onboarding/checklist"),
    refetchInterval: poll ? 2000 : false,
  });
