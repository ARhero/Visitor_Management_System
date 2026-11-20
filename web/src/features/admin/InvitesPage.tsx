import { PageHeader, Spinner } from "@/components/ui";
import "../staff/i18n";
import { InvitesView } from "../invites/Invites";
import { usePurposes, useSites, useUsers } from "./queries";

export default function InvitesPage() {
  const sites = useSites();
  const hosts = useUsers({ role: "host", limit: 500 });
  const purposes = usePurposes();
  if (!sites.data || !hosts.data) return <Spinner />;
  return (
    <>
      <PageHeader
        title="Invites"
        description="Pre-approved visits. Guests get a pass on WhatsApp and are let in without waiting for the host. Hosts manage their own invites from their phone; here you see and manage everyone's."
      />
      <InvitesView
        sites={sites.data.filter((s) => s.is_active).map((s) => ({ id: s.id, name: s.name }))}
        hosts={hosts.data.items.map((u) => ({ id: u.id, name: u.full_name }))}
        purposes={(purposes.data ?? []).filter((p) => p.is_active).map((p) => ({ id: p.id, label: p.label }))}
      />
    </>
  );
}
