import type { NextAuthOptions, Profile } from "next-auth";

const issuer = process.env.OIDC_ISSUER ?? "";

function profileString(
  profile: Profile,
  key: "sub" | "name" | "email",
): string | null {
  const value = profile[key];
  return typeof value === "string" && value.trim() ? value : null;
}

export const authOptions: NextAuthOptions = {
  secret: process.env.NEXTAUTH_SECRET,
  session: { strategy: "jwt", maxAge: 60 * 60 * 8 },
  providers: [
    {
      id: "oidc",
      name: "Single sign-on",
      type: "oauth",
      wellKnown: `${issuer.replace(/\/$/, "")}/.well-known/openid-configuration`,
      clientId: process.env.OIDC_CLIENT_ID ?? "",
      clientSecret: process.env.OIDC_CLIENT_SECRET ?? "",
      authorization: { params: { scope: "openid profile email" } },
      idToken: true,
      checks: ["pkce", "state"],
      profile(profile) {
        const id = profileString(profile, "sub");
        if (id === null) {
          throw new Error("The identity provider profile has no subject");
        }
        return {
          id,
          name: profileString(profile, "name"),
          email: profileString(profile, "email"),
          image: null,
        };
      },
    },
  ],
  callbacks: {
    async jwt({ token, account }) {
      if (account?.access_token) {
        token.accessToken = account.access_token;
      }
      if (account?.expires_at) {
        token.accessTokenExpiresAt = account.expires_at;
      }
      return token;
    },
    async session({ session }) {
      return session;
    },
  },
  pages: { signIn: "/login" },
};
