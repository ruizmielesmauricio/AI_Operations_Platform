export const metadata = {
  title: "Subscription confirmed — ORLA",
};

export default async function BillingSuccessPage({
  searchParams,
}: {
  searchParams: Promise<{ session_id?: string }>;
}) {
  const { session_id: sessionId } = await searchParams;

  return (
    <main>
      <h1>You're all set</h1>
      <p>
        Your subscription is being set up. Access is granted automatically once
        Stripe confirms payment — this usually takes a few seconds, but never
        requires you to do anything further on this page.
      </p>
      {sessionId && (
        <p>
          Reference: <code>{sessionId}</code>
        </p>
      )}
      <p>Stripe emails your receipt to the address used at checkout.</p>
      <p>
        <a href="/onboarding">Back to Company Profile</a> · <a href="/uploads">Upload your data</a> ·{" "}
        <a href="/dashboard">Go to Dashboard</a>
      </p>
    </main>
  );
}
