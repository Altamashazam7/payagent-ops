import { getServerSession } from "next-auth";
import { redirect } from "next/navigation";

import { LoginButton } from "@/app/login/login-button";
import { authOptions, isDemoAuthEnabled } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function LoginPage() {
  const session = await getServerSession(authOptions);
  if (session) {
    redirect("/dashboard");
  }
  const configured = Boolean(
    process.env.OIDC_ISSUER &&
      process.env.OIDC_CLIENT_ID &&
      process.env.OIDC_CLIENT_SECRET &&
      process.env.NEXTAUTH_SECRET,
  );

  return (
    <main className="login-page">
      <section className="login-visual">
        <a className="brand-lockup" href="/login">
          <span className="brand-mark">P</span>
          <span>
            <strong>PayAgent</strong>
            <small>OPS CONSOLE</small>
          </span>
        </a>
        <div>
          <h1>
            Commerce,
            <br />
            <span>under control.</span>
          </h1>
          <p>
            One operational surface for disputes, receivables, payouts, and
            agent recommendations—with people in control of every financial
            action.
          </p>
        </div>
        <div className="eyebrow">AUTONOMOUS INSIGHT. HUMAN AUTHORITY.</div>
      </section>
      <section className="login-panel">
        <div className="login-card">
          <div className="eyebrow">SECURE WORKSPACE</div>
          <h2>Sign in to PayAgent Ops</h2>
          <p>
            Use your organization account to access tenant-scoped commerce
            operations.
          </p>
          <LoginButton
            configured={configured}
            demoEnabled={isDemoAuthEnabled}
          />
        </div>
      </section>
    </main>
  );
}
