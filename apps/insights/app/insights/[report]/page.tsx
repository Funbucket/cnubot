import { headers } from "next/headers";
import { notFound } from "next/navigation";
import { authFailure } from "@/lib/auth";
import { isReport, kstDate, reports } from "@/lib/reports";
import Dashboard from "@/components/dashboard";

export const dynamic = "force-dynamic";
export async function generateMetadata({
  params,
}: {
  params: Promise<{ report: string }>;
}) {
  const { report } = await params;
  return { title: isReport(report) ? reports[report].label : "보고서" };
}
export default async function Page({
  params,
}: {
  params: Promise<{ report: string }>;
}) {
  if (authFailure((await headers()).get("authorization")))
    return (
      <main className="unavailable">
        관리자 인증이 필요합니다. 페이지를 새로고침해 주세요.
      </main>
    );
  const { report } = await params;
  if (!isReport(report)) notFound();
  return <Dashboard report={report} today={kstDate()} />;
}
