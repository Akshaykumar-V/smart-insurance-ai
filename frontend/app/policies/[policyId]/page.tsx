import { PolicyWorkspace } from "@/components/policy-workspace";

export default async function PolicyPage({ params }: { params: Promise<{ policyId: string }> }) {
  const { policyId } = await params;
  return <PolicyWorkspace key={policyId} policyId={policyId} view="details" />;
}
