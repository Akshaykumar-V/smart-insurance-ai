import { AppEntry } from "@/components/app-entry";

export default async function FindingsPage({ params }: { params: Promise<{ policyId: string }> }) {
  const { policyId } = await params;
  return <AppEntry route={{ policyId, view: "findings" }} />;
}
