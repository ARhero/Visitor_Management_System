import { useRef, useState } from "react";
import { Alert, Button } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import type { Org } from "@/lib/types";
import { keys, useMut } from "./queries";

/** Upload / replace / remove the organization's logo (PNG or JPEG, up to 2 MB). */
export function LogoUpload({ org }: { org: Org }) {
  const input = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);
  const upload = useMut((file: File) => {
    const body = new FormData();
    body.append("file", file);
    return api<Org>("/org/logo", { method: "POST", body });
  }, [keys.org]);
  const remove = useMut(() => api<Org>("/org/logo", { method: "DELETE" }), [keys.org]);

  return (
    <div>
      <div className="flex items-center gap-4">
        <div className="grid size-16 shrink-0 place-items-center overflow-hidden rounded-lg border border-line bg-paper">
          {org.logo_url ? <img src={org.logo_url} alt={`${org.name} logo`} className="size-full object-contain p-1.5" />
            : <span className="text-xl font-semibold text-ink-3">{org.name.slice(0, 1)}</span>}
        </div>
        <div className="space-y-1">
          <div className="flex flex-wrap gap-2">
            <Button type="button" size="sm" variant="secondary" busy={upload.isPending} onClick={() => input.current?.click()}>
              {org.logo_url ? "Replace logo" : "Upload logo"}
            </Button>
            {org.logo_url && (
              <Button type="button" size="sm" variant="ghost" busy={remove.isPending} onClick={() => remove.mutate(undefined)}>Remove</Button>
            )}
          </div>
          <p className="text-xs text-ink-3">PNG or JPEG, up to 2 MB. A square logo on a transparent background prints best.</p>
        </div>
        <input ref={input} type="file" accept="image/png,image/jpeg" className="hidden" aria-label="Logo file"
          onChange={(e) => {
            const file = e.target.files?.[0];
            e.target.value = "";
            if (!file) return;
            setError(null);
            upload.mutate(file, { onError: (err) => setError(errorMessage(err)) });
          }} />
      </div>
      {error && <div className="mt-3"><Alert>{error}</Alert></div>}
    </div>
  );
}
