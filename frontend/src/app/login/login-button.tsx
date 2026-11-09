"use client";

import { signIn } from "next-auth/react";

export function LoginButton({ configured }: { configured: boolean }) {
  return (
    <>
      <button
        className="button button-primary"
        disabled={!configured}
        onClick={() => void signIn("oidc", { callbackUrl: "/dashboard" })}
        type="button"
      >
        Continue with single sign-on
      </button>
      {!configured ? (
        <div className="login-note" role="status">
          Configure the OIDC issuer, client credentials, and session secret to
          enable sign-in.
        </div>
      ) : (
        <div className="login-note">
          Your organization identity provider controls access and roles.
        </div>
      )}
    </>
  );
}
