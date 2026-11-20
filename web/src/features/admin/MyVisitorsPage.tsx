import { PageHeader } from "@/components/ui";
import { HostTabs } from "../host/HostApp";

/** The host screen inside the admin panel, for admins who are also hosts. */
export default function MyVisitorsPage() {
  return (
    <>
      <PageHeader title="My visitors" description="People who came to see you: answer requests, see your history and invite guests." />
      <HostTabs wide />
    </>
  );
}
