import { Link } from "react-router";
import { Button, Card, cx } from "@/components/ui";
import { api } from "@/lib/api";
import { useMut } from "./queries";
import { useChecklist } from "./onboardingApi";

const LINKS: Record<string, string> = {
  org: "/admin/setup?step=org",
  site: "/admin/setup?step=site",
  hosts: "/admin/setup?step=hosts",
  form: "/admin/setup?step=form",
  posters: "/admin/setup?step=posters",
  test_visit: "/admin/setup?step=test_visit",
  guard: "/admin/people",
};

/** The getting-started checklist: on the dashboard until every step is done or it is hidden. */
export function SetupChecklist() {
  const { data } = useChecklist();
  const dismiss = useMut(() => api("/onboarding/dismiss", { method: "POST" }), [["onboarding"]]);
  if (!data || data.complete || data.dismissed) return null;
  return (
    <Card
      title="Setup checklist"
      actions={
        <span className="flex items-center gap-3">
          <span className="text-sm text-ink-2">{data.done} of {data.total}</span>
          <Link to="/admin/setup"><Button size="sm">Continue setup</Button></Link>
          <Button size="sm" variant="ghost" busy={dismiss.isPending} onClick={() => dismiss.mutate(undefined)}>Hide</Button>
        </span>
      }
      padded={false}
      className="mb-6"
    >
      <div className="h-1 bg-line">
        <div className="h-1 bg-brand transition-all" style={{ width: `${(data.done / data.total) * 100}%` }} />
      </div>
      <ol className="grid divide-y divide-line sm:grid-cols-2 sm:divide-y-0">
        {data.steps.map((s, i) => (
          <li key={s.key} className="sm:border-b sm:border-line sm:odd:border-r">
            <Link to={LINKS[s.key] ?? "/admin/setup"} className="flex items-center gap-4 px-5 py-3 hover:bg-paper">
              <span className={cx("grid size-7 shrink-0 place-items-center rounded-full border text-xs font-semibold",
                s.done ? "border-brand bg-brand text-white" : "border-line-strong text-ink-3")}>
                {s.done ? "✓" : i + 1}
              </span>
              <span className="min-w-0 flex-1">
                <span className={cx("block text-sm font-medium", s.done && "text-ink-2")}>{s.label}</span>
                <span className="block truncate text-xs text-ink-3">{s.detail}</span>
              </span>
              {!s.done && <span className="text-sm text-brand">Start →</span>}
            </Link>
          </li>
        ))}
      </ol>
    </Card>
  );
}
