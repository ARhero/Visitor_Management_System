import type { HostOption, Prefill } from "./publicApi";

/** Check-in form state, shared by the first steps (phone, code) and the later ones. */
export const ID_TYPES = ["aadhaar", "pan", "driving_licence", "voter_id", "passport", "company_id", "other"] as const;

export interface Session { token: string; phone: string; exp: number; prefill: Prefill | null }
export interface Form {
  full_name: string; company: string; host: HostOption | null; purpose_id: string; purpose_note: string;
  accompanying_count: number; vehicle_number: string; custom: Record<string, unknown>;
  id_type: string; id_last4: string; photo_upload: string | null; photo_preview: string | null; use_previous_photo: boolean;
}
export const emptyForm: Form = {
  full_name: "", company: "", host: null, purpose_id: "", purpose_note: "", accompanying_count: 0, vehicle_number: "",
  custom: {}, id_type: "", id_last4: "", photo_upload: null, photo_preview: null, use_previous_photo: false,
};

export function fromPrefill(p: Prefill | null | undefined): Form {
  return { ...emptyForm, full_name: p?.full_name ?? "", company: p?.company ?? "", host: p?.last_host ?? null, use_previous_photo: !!p?.has_photo };
}
