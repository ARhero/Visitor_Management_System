import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Alert, Button, Checkbox, Field, Input, Select, Spinner, cx } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { compressImage } from "@/lib/image";
import { errText, useS } from "../staff/i18n";
import type { GuardCard, GuardForm, GuardSite } from "./guardApi";

interface Host {
  id: string;
  full_name: string;
  department: string | null;
  designation: string | null;
}

const ID_TYPES = ["aadhaar", "pan", "driving_licence", "voter_id", "passport", "company_id", "other"];

function HostPicker({ value, onChange }: { value: Host | null; onChange: (h: Host | null) => void }) {
  const { t } = useS();
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  useEffect(() => {
    const id = setTimeout(() => setDebounced(q.trim()), 200);
    return () => clearTimeout(id);
  }, [q]);
  const res = useQuery({
    queryKey: ["directory", debounced],
    queryFn: () => api<Host[]>("/users/directory", { query: { q: debounced, limit: 8 } }),
    enabled: debounced.length >= 2 && !value,
  });
  if (value) {
    return (
      <div className="flex items-center justify-between rounded-lg border border-brand/40 bg-brand-50 px-3 py-2">
        <div>
          <p className="font-medium">{value.full_name}</p>
          <p className="text-xs text-ink-2">{[value.designation, value.department].filter(Boolean).join(" · ")}</p>
        </div>
        <button type="button" className="text-sm text-brand" onClick={() => onChange(null)}>✕</button>
      </div>
    );
  }
  return (
    <div>
      <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("guard.walkin.hostSearch")} autoComplete="off" data-testid="host-search" />
      {debounced.length >= 2 && (
        <ul className="mt-1 divide-y divide-line overflow-hidden rounded-lg border border-line">
          {res.isLoading && <li className="px-3 py-2 text-sm text-ink-3">{t("common.loading")}…</li>}
          {res.data?.length === 0 && <li className="px-3 py-2 text-sm text-ink-3">{t("guard.walkin.noHosts")}</li>}
          {res.data?.map((h) => (
            <li key={h.id}>
              <button type="button" className="w-full px-3 py-2 text-left hover:bg-paper" onClick={() => onChange(h)}>
                <span className="font-medium">{h.full_name}</span>
                <span className="block text-xs text-ink-3">{[h.designation, h.department].filter(Boolean).join(" · ")}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function WalkInForm({ site, form }: { site: GuardSite; form?: GuardForm }) {
  const { t, i18n } = useS();
  const lang = i18n.language;
  const empty = { phone: "", full_name: "", company: "", purpose_id: "", purpose_note: "", accompanying_count: 0, vehicle_number: "", id_type: "", id_last4: "", otp: "", reason: "" };
  const [v, setV] = useState(empty);
  const [host, setHost] = useState<Host | null>(null);
  const [custom, setCustom] = useState<Record<string, unknown>>({});
  const [photo, setPhoto] = useState<{ blob: Blob; url: string } | null>(null);
  const [consent, setConsent] = useState(false);
  const [showNotice, setShowNotice] = useState(false);
  const [admit, setAdmit] = useState(false);
  const [otpSent, setOtpSent] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<GuardCard | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const gate = site.gates[0];

  if (!form) return <Spinner label={t("common.loading")} />;
  const notice = form.notices[lang] ?? form.notices.en;
  const purpose = form.purposes.find((p) => p.id === v.purpose_id);
  const idShown = form.id_proof_mode !== "off" || purpose?.requires_id_proof;
  const idRequired = form.id_proof_mode === "required" || purpose?.requires_id_proof;
  const set = (k: keyof typeof empty) => (e: { target: { value: string } }) => setV({ ...v, [k]: e.target.value });

  async function sendOtp() {
    setError(null);
    try {
      const r = await api<{ sent_to: string }>("/guard/otp/send", { method: "POST", body: { site_id: site.id, phone: v.phone, locale: lang } });
      setOtpSent(r.sent_to);
    } catch (e) {
      setError(errText(e));
    }
  }

  async function onPhoto(file: File | undefined) {
    if (!file) return;
    const blob = await compressImage(file, 640);
    setPhoto({ blob, url: URL.createObjectURL(blob) });
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      let photo_upload: string | undefined;
      if (photo) {
        const fd = new FormData();
        fd.append("file", photo.blob, "photo.webp");
        fd.append("kind", "selfie");
        photo_upload = (await api<{ upload_token: string }>("/guard/uploads", { method: "POST", body: fd })).upload_token;
      }
      const card = await api<GuardCard>("/guard/visits", {
        method: "POST",
        body: {
          site_id: site.id,
          gate_id: gate?.id,
          phone: v.phone,
          full_name: v.full_name,
          company: v.company || undefined,
          host_id: host?.id,
          purpose_id: v.purpose_id,
          purpose_note: v.purpose_note || undefined,
          accompanying_count: Number(v.accompanying_count) || 0,
          vehicle_number: v.vehicle_number || undefined,
          id_type: idShown && v.id_type ? v.id_type : undefined,
          id_last4: idShown && v.id_last4 ? v.id_last4 : undefined,
          custom_values: custom,
          photo_upload,
          consent_notice_id: notice?.id,
          consent,
          locale: lang,
          otp_code: form!.otp_required ? v.otp : undefined,
          admit,
          override_reason: admit ? v.reason : undefined,
        },
      });
      setDone(card);
    } catch (err) {
      if (err instanceof ApiError && err.code === "blocked") {
        setError(t("guard.walkin.blocked", { reason: (err.details as { reason?: string })?.reason ?? "" }));
      } else setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  function reset() {
    setV(empty);
    setHost(null);
    setCustom({});
    setPhoto(null);
    setConsent(false);
    setAdmit(false);
    setOtpSent(null);
    setDone(null);
    setError(null);
  }

  if (done) {
    return (
      <div className="space-y-4 rounded-2xl border border-line bg-surface p-6 text-center" data-testid="walkin-done" data-status={done.status}>
        <p className="text-lg font-semibold">
          {done.status === "checked_in" ? t("guard.walkin.checkedIn", { name: done.visitor_name }) : t("guard.walkin.sentToHost", { host: done.host_name })}
        </p>
        <Button size="lg" onClick={reset}>{t("guard.walkin.another")}</Button>
      </div>
    );
  }

  const canSubmit = host && v.purpose_id && consent && (!form.require_selfie || photo) && (!admit || v.reason.trim().length >= 3) && (!form.otp_required || v.otp.length === 6);

  return (
    <form onSubmit={submit} className="space-y-4 rounded-2xl border border-line bg-surface p-5">
      <h2 className="font-semibold">{t("guard.walkin.title")}</h2>
      <Field label={t("guard.walkin.phone")}>
        {(id) => <Input id={id} type="tel" inputMode="tel" required value={v.phone} onChange={set("phone")} autoComplete="off" />}
      </Field>
      {form.otp_required && (
        <Field label={t("guard.walkin.otp")} hint={otpSent ? t("guard.walkin.otpSent", { to: otpSent }) : undefined}>
          {(id) => (
            <div className="flex gap-2">
              <Input id={id} inputMode="numeric" maxLength={6} value={v.otp} onChange={set("otp")} />
              <Button type="button" variant="secondary" disabled={v.phone.length < 10} onClick={() => void sendOtp()}>{t("guard.walkin.sendOtp")}</Button>
            </div>
          )}
        </Field>
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t("guard.walkin.name")}>{(id) => <Input id={id} required value={v.full_name} onChange={set("full_name")} />}</Field>
        <Field label={t("guard.walkin.company")}>{(id) => <Input id={id} value={v.company} onChange={set("company")} />}</Field>
      </div>
      <div className="space-y-1.5">
        <p className="text-sm font-medium">{t("guard.walkin.host")}</p>
        <HostPicker value={host} onChange={setHost} />
      </div>
      <Field label={t("guard.walkin.purpose")}>
        {(id) => (
          <Select id={id} required value={v.purpose_id} onChange={set("purpose_id")}>
            <option value="">{t("guard.walkin.choose")}</option>
            {form.purposes.map((p) => <option key={p.id} value={p.id}>{p.label_i18n[lang] || p.label}</option>)}
          </Select>
        )}
      </Field>
      <Field label={t("guard.walkin.note")}>{(id) => <Input id={id} value={v.purpose_note} onChange={set("purpose_note")} maxLength={500} />}</Field>
      <div className="grid grid-cols-2 gap-4">
        <Field label={t("guard.walkin.people")}>{(id) => <Input id={id} type="number" min={0} max={20} value={v.accompanying_count} onChange={set("accompanying_count")} />}</Field>
        <Field label={t("guard.walkin.vehicle")}>{(id) => <Input id={id} value={v.vehicle_number} onChange={set("vehicle_number")} maxLength={20} />}</Field>
      </div>
      {idShown && (
        <div className="grid grid-cols-2 gap-4">
          <Field label={t("guard.walkin.idType")}>
            {(id) => (
              <Select id={id} required={!!idRequired} value={v.id_type} onChange={set("id_type")}>
                <option value="">{t("guard.walkin.choose")}</option>
                {ID_TYPES.map((x) => <option key={x} value={x}>{t(`guard.ids.${x}`)}</option>)}
              </Select>
            )}
          </Field>
          <Field label={t("guard.walkin.idLast4")} hint={t("guard.walkin.idHelp")}>
            {(id) => <Input id={id} required={!!idRequired} maxLength={4} pattern="[0-9A-Za-z]{4}" value={v.id_last4} onChange={set("id_last4")} />}
          </Field>
        </div>
      )}
      {form.fields.map((fd) => {
        const label = fd.label_i18n[lang] || fd.label;
        const val = custom[fd.key];
        const put = (x: unknown) => setCustom({ ...custom, [fd.key]: x });
        if (fd.type === "checkbox" || fd.type === "declaration")
          return <Checkbox key={fd.key} label={label} checked={!!val} required={fd.required} onChange={(e) => put(e.target.checked)} />;
        return (
          <Field key={fd.key} label={label + (fd.required ? " *" : "")}>
            {(id) =>
              fd.type === "select" ? (
                <Select id={id} required={fd.required} value={String(val ?? "")} onChange={(e) => put(e.target.value)}>
                  <option value="">{t("guard.walkin.choose")}</option>
                  {fd.options.map((o) => <option key={o}>{o}</option>)}
                </Select>
              ) : (
                <Input id={id} type={fd.type === "number" ? "number" : "text"} required={fd.required} value={String(val ?? "")} onChange={(e) => put(e.target.value)} />
              )
            }
          </Field>
        );
      })}
      <div className="space-y-2">
        <p className="text-sm font-medium">{t("guard.walkin.photo")}{form.require_selfie && " *"}</p>
        <div className="flex items-center gap-3">
          {photo && <img src={photo.url} alt="" className="size-20 rounded-xl object-cover ring-1 ring-line" />}
          <Button type="button" variant="secondary" onClick={() => fileRef.current?.click()}>{photo ? t("guard.walkin.retake") : t("guard.walkin.takePhoto")}</Button>
          <input ref={fileRef} type="file" accept="image/*" capture="environment" className="hidden" data-testid="walkin-photo" onChange={(e) => void onPhoto(e.target.files?.[0])} />
        </div>
      </div>
      <div className="space-y-2 rounded-lg bg-paper p-3">
        <Checkbox label={t("guard.walkin.consent")} checked={consent} onChange={(e) => setConsent(e.target.checked)} />
        <button type="button" className="text-sm font-medium text-brand" onClick={() => setShowNotice(!showNotice)}>{t("guard.walkin.showNotice")}</button>
        {showNotice && notice && <div className="max-h-60 overflow-y-auto whitespace-pre-line text-sm text-ink-2">{notice.body}</div>}
      </div>
      <fieldset className="space-y-2">
        <legend className="mb-1 text-sm font-medium">{t("guard.walkin.decision")}</legend>
        {[false, true].map((a) => (
          <label key={String(a)} className={cx("flex cursor-pointer items-center gap-3 rounded-lg border px-3 py-2.5 text-sm", admit === a ? "border-brand bg-brand-50" : "border-line")}>
            <input type="radio" name="decision" checked={admit === a} onChange={() => setAdmit(a)} className="accent-brand" />
            {a ? t("guard.walkin.admitNow") : t("guard.walkin.askHost")}
          </label>
        ))}
        {admit && (
          <Field label={t("guard.actions.reason")} hint={t("guard.actions.admitHelp")}>
            {(id) => <Input id={id} value={v.reason} onChange={set("reason")} maxLength={300} placeholder={t("guard.actions.reasonPlaceholder")} />}
          </Field>
        )}
      </fieldset>
      {error && <Alert>{error}</Alert>}
      <Button type="submit" size="lg" className="w-full" busy={busy} disabled={!canSubmit}>
        {admit ? t("guard.walkin.submit") : t("guard.walkin.submitAsk")}
      </Button>
    </form>
  );
}

