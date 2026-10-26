import { PolicyWorkspace } from "@/components/policy-workspace";

export default async function FindingsPage({ params }: { params: Promise<{ policyId: string }> }) {
  const { policyId } = await params;
  return <PolicyWorkspace key={policyId} policyId={policyId} view="findings" />;
}
