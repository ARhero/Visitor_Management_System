import { useParams } from "react-router";
import { PassCard, usePass } from "./PassCard";
import { PublicShell } from "./PublicShell";

export default function PassPage() {
  const { passToken = "" } = useParams();
  const q = usePass(passToken);
  return (
    <PublicShell org={q.data?.org_name} sub={q.data?.site_name} color={q.data?.branding.primary_color}>
      <PassCard token={passToken} />
    </PublicShell>
  );
}
