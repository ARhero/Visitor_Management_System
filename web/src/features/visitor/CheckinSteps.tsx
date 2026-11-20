import { useEffect, useRef, useState } from "react";
import { Field, Input, Select, cx } from "@/components/ui";
import { compressImage } from "@/lib/image";
import { BigButton, Linkified, Panel } from "./PublicShell";
import { useT } from "./i18n";
import { label, pub, type CustomField, type GateInfo, type HostOption } from "./publicApi";
import { ID_TYPES, type Form, type Session } from "./checkinForm";
import { useLoad } from "./useLoad";

/** Check-in steps after the number is verified: details, photo, confirm. A separate chunk:
 *  it loads while the visitor types their number, so the first screen appears sooner. */

function HostPicker({ token, value, onChange, onError }: {
  token: string; value: HostOption | null; onChange: (h: HostOption | null) => void; onError: (e: unknown) => void;
}) {
  const { t } = useT();
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  useEffect(() => {
    const id = setTimeout(() => setDebounced(q.trim()), 250);
    return () => clearTimeout(id);
  }, [q]);
  const res = useLoad(`hosts:${debounced}`, () => pub<HostOption[]>(`/hosts?q=${encodeURIComponent(debounced)}`, { token }), {
    enabled: debounced.length >= 2 && !value,
  });
  useEffect(() => { if (res.error) onError(res.error); }, [res.error, onError]);

  if (value) {
    return (
      <div className="flex items-center justify-between rounded-lg border border-brand/40 bg-brand-50 px-3 py-2.5">
        <div className="min-w-0">
          <p className="truncate font-medium">{value.full_name}</p>
          <p className="truncate text-xs text-ink-2">{[value.designation, value.department].filter(Boolean).join(" · ")}</p>
        </div>
        <button type="button" className="shrink-0 text-sm text-brand" onClick={() => { onChange(null); setQ(""); }}>{t("details.change")}</button>
      </div>
    );
  }
  return (
    <div>
      <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("details.hostSearch")} className="h-12 text-base"
        autoComplete="off" aria-label={t("details.host")} />
      {debounced.length < 2 ? (
        <p className="mt-1 text-xs text-ink-3">{t("details.hostHint")}</p>
      ) : res.isFetching && !res.data ? (
        <p className="mt-2 text-sm text-ink-3">…</p>
      ) : res.data?.length === 0 ? (
        <p className="mt-2 text-sm text-ink-2">{t("details.noHosts")}</p>
      ) : (
        <ul className="mt-2 divide-y divide-line overflow-hidden rounded-lg border border-line">
          {res.data?.map((h) => (
            <li key={h.id}>
              <button type="button" className="w-full px-3 py-2.5 text-left hover:bg-paper" onClick={() => onChange(h)}>
                <span className="block font-medium">{h.full_name}</span>
                <span className="block text-xs text-ink-2">{[h.designation, h.department].filter(Boolean).join(" · ")}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function idNeeded(g: GateInfo, purposeId: string) {
  const p = g.purposes.find((x) => x.id === purposeId);
  return { show: g.id_proof_mode !== "off" || !!p?.requires_id_proof, required: g.id_proof_mode === "required" || !!p?.requires_id_proof };
}

export function DetailsStep({ g, session, form, setForm, lang, onNext, onError }: {
  g: GateInfo; session: Session; form: Form; setForm: (f: Form) => void; lang: string; onNext: () => void; onError: (e: unknown) => void;
}) {
  const { t } = useT();
  const [touched, setTouched] = useState(false);
  const set = (patch: Partial<Form>) => setForm({ ...form, ...patch });
  const id = idNeeded(g, form.purpose_id);
  const missing = (f: CustomField) => {
    const v = form.custom[f.key];
    return (f.required || f.type === "declaration") && (v === undefined || v === "" || v === false);
  };
  const nameOk = form.full_name.trim().length >= 2;
  const valid =
    nameOk && form.host && form.purpose_id && !g.fields.some(missing) &&
    (!id.required || (form.id_type && /^[0-9A-Za-z]{4}$/.test(form.id_last4)));
  const req = (bad: boolean) => (touched && bad ? t("details.required") : null);

  return (
    <Panel>
      <h1 className="text-xl font-semibold">{t("details.title")}</h1>
      {session.prefill?.full_name && <p className="mt-1 text-sm text-ink-2">{t("details.welcomeBack", { name: session.prefill.full_name })}</p>}
      <form className="mt-5 space-y-5" noValidate onSubmit={(e) => {
        e.preventDefault();
        setTouched(true);
        if (valid) return onNext();
        // Bring the first problem into view (on a phone it is often off screen).
        setTimeout(() => {
          const err = document.querySelector("[data-field-error]");
          const box = err?.parentElement;
          box?.scrollIntoView({ block: "center", behavior: "smooth" });
          box?.querySelector<HTMLElement>("input:not([type=radio]), select, button")?.focus({ preventScroll: true });
        }, 0);
      }}>
        {touched && !valid && <p className="rounded-lg bg-bad-50 px-3 py-2 text-sm text-bad" role="alert">{t("details.fixErrors")}</p>}
        <Field label={t("details.name")} error={req(!nameOk)}>
          {(i) => <Input id={i} required autoComplete="name" value={form.full_name} onChange={(e) => set({ full_name: e.target.value })} className="h-12 text-base" />}
        </Field>
        <Field label={t("details.company")} hint={t("details.optional")}>
          {(i) => <Input id={i} autoComplete="organization" value={form.company} onChange={(e) => set({ company: e.target.value })} className="h-12 text-base" />}
        </Field>
        <div className="space-y-1.5">
          <p className="text-sm font-medium">{t("details.host")}</p>
          <HostPicker token={session.token} value={form.host} onChange={(h) => set({ host: h })} onError={onError} />
          {touched && !form.host && <p className="text-sm text-bad" data-field-error>{t("details.required")}</p>}
        </div>
        <fieldset className="space-y-1.5">
          <legend className="mb-1.5 text-sm font-medium">{t("details.purpose")}</legend>
          <div className="grid grid-cols-2 gap-2">
            {g.purposes.map((p) => (
              <label key={p.id} className={cx("flex min-h-12 cursor-pointer items-center rounded-lg border px-3 py-2 text-sm",
                form.purpose_id === p.id ? "border-brand bg-brand-50 font-medium text-brand" : "border-line-strong bg-surface")}>
                <input type="radio" name="purpose" className="sr-only" checked={form.purpose_id === p.id} onChange={() => set({ purpose_id: p.id })} />
                {label(p, lang)}
              </label>
            ))}
          </div>
          {touched && !form.purpose_id && <p className="text-sm text-bad" data-field-error>{t("details.required")}</p>}
        </fieldset>
        <Field label={t("details.note")} hint={t("details.optional")}>
          {(i) => <Input id={i} value={form.purpose_note} maxLength={500} placeholder={t("details.notePlaceholder")} onChange={(e) => set({ purpose_note: e.target.value })} className="h-12 text-base" />}
        </Field>
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium">{t("details.people")}</span>
          <div className="flex items-center gap-3">
            <button type="button" className="size-10 rounded-lg border border-line-strong text-lg" aria-label="−"
              onClick={() => set({ accompanying_count: Math.max(0, form.accompanying_count - 1) })}>−</button>
            <span className="w-6 text-center text-lg font-medium" aria-live="polite">{form.accompanying_count}</span>
            <button type="button" className="size-10 rounded-lg border border-line-strong text-lg" aria-label="+"
              onClick={() => set({ accompanying_count: Math.min(20, form.accompanying_count + 1) })}>+</button>
          </div>
        </div>
        <Field label={t("details.vehicle")} hint={t("details.vehicleHint")}>
          {(i) => <Input id={i} value={form.vehicle_number} maxLength={20} autoCapitalize="characters" placeholder="OD 02 AB 1234"
            onChange={(e) => set({ vehicle_number: e.target.value.toUpperCase() })} className="h-12 text-base uppercase" />}
        </Field>

        {g.fields.map((f) => <CustomInput key={f.key} f={f} lang={lang} value={form.custom[f.key]} error={req(missing(f))}
          onChange={(v) => set({ custom: { ...form.custom, [f.key]: v } })} />)}

        {id.show && (
          <div className="grid grid-cols-2 gap-3">
            <Field label={t("details.idType")} error={req(id.required && !form.id_type)}>
              {(i) => (
                <Select id={i} value={form.id_type} onChange={(e) => set({ id_type: e.target.value })} className="h-12 text-base">
                  <option value="">{t("details.choose")}</option>
                  {ID_TYPES.map((x) => <option key={x} value={x}>{t(`idTypes.${x}`)}</option>)}
                </Select>
              )}
            </Field>
            <Field label={t("details.idLast4")} error={req(id.required && !/^[0-9A-Za-z]{4}$/.test(form.id_last4))}>
              {(i) => <Input id={i} value={form.id_last4} maxLength={4} inputMode="text" autoComplete="off" className="h-12 font-mono text-base tracking-widest"
                onChange={(e) => set({ id_last4: e.target.value.replace(/[^0-9A-Za-z]/g, "").slice(0, 4) })} />}
            </Field>
            <p className="col-span-2 -mt-1 text-xs text-ink-3">{t("details.idHint")}</p>
          </div>
        )}
        <BigButton type="submit">{t("details.next")}</BigButton>
      </form>
    </Panel>
  );
}

function CustomInput({ f, lang, value, error, onChange }: {
  f: CustomField; lang: string; value: unknown; error: string | null; onChange: (v: unknown) => void;
}) {
  const { t } = useT();
  const text = label(f, lang);
  const help = f.help_i18n[lang] || f.help_i18n.en;
  if (f.type === "checkbox" || f.type === "declaration") {
    return (
      <div>
        <label className={cx("flex cursor-pointer items-start gap-3 rounded-lg border p-3", f.type === "declaration" ? "border-line-strong bg-paper" : "border-line")}>
          <input type="checkbox" className="mt-0.5 size-5 accent-brand" checked={value === true} onChange={(e) => onChange(e.target.checked)} />
          <span className="text-sm">{text}{help && <span className="mt-0.5 block text-xs text-ink-3">{help}</span>}</span>
        </label>
        {error && <p className="mt-1 text-sm text-bad" data-field-error>{error}</p>}
      </div>
    );
  }
  return (
    <Field label={text} hint={help || (f.required ? undefined : t("details.optional"))} error={error}>
      {(i) =>
        f.type === "select" ? (
          <Select id={i} value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} className="h-12 text-base">
            <option value="">{t("details.choose")}</option>
            {f.options.map((o) => <option key={o} value={o}>{o}</option>)}
          </Select>
        ) : (
          <Input id={i} type={f.type === "number" ? "number" : "text"} inputMode={f.type === "number" ? "decimal" : undefined}
            value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} className="h-12 text-base" />
        )
      }
    </Field>
  );
}

export function PhotoStep({ g, session, form, setForm, onNext, onError }: {
  g: GateInfo; session: Session; form: Form; setForm: (f: Form) => void; onNext: () => void; onError: (e: unknown) => void;
}) {
  const { t } = useT();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);

  async function picked(file: File | undefined) {
    if (!file) return;
    setBusy(true);
    try {
      const small = await compressImage(file);
      const fd = new FormData();
      fd.append("file", small, "photo.webp");
      fd.append("kind", "selfie");
      const r = await pub<{ upload_token: string }>("/uploads", { token: session.token, body: fd });
      if (form.photo_preview) URL.revokeObjectURL(form.photo_preview);
      setForm({ ...form, photo_upload: r.upload_token, photo_preview: URL.createObjectURL(small), use_previous_photo: false });
    } catch (err) {
      onError(err);
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }
  const hasPhoto = !!form.photo_upload || form.use_previous_photo;
  return (
    <Panel>
      <h1 className="text-xl font-semibold">{t("photo.title")}</h1>
      <p className="mt-1 text-sm text-ink-2">{t("photo.help")}</p>
      <div className="mt-5 flex flex-col items-center gap-4">
        <div className="flex size-44 items-center justify-center overflow-hidden rounded-full border-4 border-surface bg-paper shadow-inner ring-1 ring-line">
          {form.photo_preview ? <img src={form.photo_preview} alt="" className="size-full object-cover" />
            : <svg viewBox="0 0 24 24" className="size-20 text-ink-3" fill="currentColor" aria-hidden><path d="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm0 2c-3.3 0-8 1.7-8 5v1h16v-1c0-3.3-4.7-5-8-5Z" /></svg>}
        </div>
        <input ref={input} type="file" accept="image/*" capture="user" className="sr-only" onChange={(e) => void picked(e.target.files?.[0])} data-testid="photo-input" />
        <button type="button" disabled={busy} onClick={() => input.current?.click()}
          className="flex h-12 w-full items-center justify-center gap-2 rounded-xl border border-brand text-base font-medium text-brand">
          {busy ? t("photo.uploading") : form.photo_upload ? t("photo.retake") : t("photo.take")}
        </button>
        {session.prefill?.has_photo && !form.photo_upload && (
          <label className="flex items-center gap-2 self-start text-sm">
            <input type="checkbox" className="size-5 accent-brand" checked={form.use_previous_photo} onChange={(e) => setForm({ ...form, use_previous_photo: e.target.checked })} />
            {t("photo.usePrevious")}
          </label>
        )}
      </div>
      <BigButton className="mt-6" disabled={busy || (g.require_selfie && !hasPhoto)} onClick={onNext}>{t("photo.next")}</BigButton>
      {g.require_selfie && !hasPhoto && !busy && <p className="mt-2 text-center text-sm text-ink-3">{t("photo.needed")}</p>}
    </Panel>
  );
}

export function ConfirmStep({ g, session, form, lang, onDone, onError }: {
  g: GateInfo; session: Session; form: Form; lang: string; onDone: (visitId: string, token: string) => void; onError: (e: unknown) => void;
}) {
  const { t } = useT();
  const [agree, setAgree] = useState(false);
  const [busy, setBusy] = useState(false);
  const notice = g.notices[lang] ?? g.notices.en;
  const purpose = g.purposes.find((p) => p.id === form.purpose_id);
  const id = idNeeded(g, form.purpose_id);

  async function submit() {
    setBusy(true);
    try {
      const custom = Object.fromEntries(Object.entries(form.custom).filter(([, v]) => v !== "" && v !== undefined));
      const r = await pub<{ visit_id: string; status_token: string }>("/visits", {
        token: session.token,
        body: {
          full_name: form.full_name.trim(),
          company: form.company.trim() || null,
          host_id: form.host!.id,
          purpose_id: form.purpose_id,
          purpose_note: form.purpose_note.trim() || null,
          accompanying_count: form.accompanying_count,
          vehicle_number: form.vehicle_number.trim() || null,
          custom_values: custom,
          photo_upload: form.photo_upload,
          use_previous_photo: !form.photo_upload && form.use_previous_photo,
          id_type: id.show && form.id_type ? form.id_type : null,
          id_last4: id.show && form.id_last4 ? form.id_last4 : null,
          consent_notice_id: notice.id,
          consent: true,
          locale: lang === "hi" ? "hi" : "en",
        },
      });
      onDone(r.visit_id, r.status_token);
    } catch (err) {
      onError(err);
      setBusy(false);
    }
  }
  return (
    <Panel>
      <h1 className="text-xl font-semibold">{t("confirm.title")}</h1>
      <dl className="mt-4 space-y-2 text-sm">
        <div className="flex gap-3"><dt className="w-24 shrink-0 text-ink-3">{t("details.name")}</dt><dd className="font-medium">{form.full_name}</dd></div>
        <div className="flex gap-3"><dt className="w-24 shrink-0 text-ink-3">{t("confirm.meeting")}</dt><dd className="font-medium">{form.host?.full_name}</dd></div>
        <div className="flex gap-3"><dt className="w-24 shrink-0 text-ink-3">{t("confirm.purpose")}</dt><dd>{purpose ? label(purpose, lang) : ""}</dd></div>
      </dl>
      <div className="mt-5 rounded-lg bg-paper p-3">
        <p className="text-sm font-medium">{t("confirm.privacy")}</p>
        <p className="mt-1 max-h-48 overflow-y-auto text-sm leading-relaxed text-ink-2"><Linkified text={notice?.body ?? ""} /></p>
        {g.privacy_url && <a href={g.privacy_url} target="_blank" rel="noreferrer" className="mt-2 inline-block text-sm font-medium text-brand underline">{t("confirm.yourData")}</a>}
      </div>
      <label className="mt-4 flex cursor-pointer items-start gap-3">
        <input type="checkbox" className="mt-0.5 size-5 accent-brand" checked={agree} onChange={(e) => setAgree(e.target.checked)} />
        <span className="text-sm">{t("confirm.agree")}</span>
      </label>
      <BigButton className="mt-5" busy={busy} disabled={!agree} onClick={() => void submit()}>{t("confirm.submit")}</BigButton>
    </Panel>
  );
}
