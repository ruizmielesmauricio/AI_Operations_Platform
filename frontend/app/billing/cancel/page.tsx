export const metadata = {
  title: "Checkout canceled — ORLA",
};

export default function BillingCancelPage() {
  return (
    <main>
      <h1>Checkout canceled</h1>
      <p>No payment was made and nothing was charged. You can start over whenever you're ready.</p>
      <p>
        <a href="/onboarding">Back to Company Profile</a>
      </p>
    </main>
  );
}
