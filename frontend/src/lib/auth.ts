import type { NextAuthOptions, Profile } from "next-auth";
import CredentialsProvider from "next-auth/providers/credentials";

const issuer = process.env.OIDC_ISSUER ?? "";
const demoExecutiveId = "1a3fd473-8734-4c50-a3d5-fd9c61b6d84e";
const demoExecutiveEmail = "demo-executive@payagent.invalid";
const demoExecutiveName = "PayAgent Demo Executive";
const demoAuthBearerToken = "payagent-ops-development-demo";

export const isDemoAuthEnabled =
  process.env.NODE_ENV === "development" &&
  process.env.DEMO_AUTH_ENABLED === "true" &&
  Boolean(process.env.NEXTAUTH_SECRET);

function profileString(
  profile: Profile,
  key: "sub" | "name" | "email",
): string | null {
  const value = profile[key];
  return typeof value === "string" && value.trim() ? value : null;
}

const providers: NextAuthOptions["providers"] = [
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
];

if (isDemoAuthEnabled) {
  providers.push(
    CredentialsProvider({
      id: "demo",
      name: "Demo executive",
      credentials: {
        demo: { label: "Development demo", type: "text" },
      },
      async authorize(credentials) {
        if (credentials?.demo !== "true") {
          return null;
        }
        return {
          id: demoExecutiveId,
          name: demoExecutiveName,
          email: demoExecutiveEmail,
        };
      },
    }),
  );
}

export const authOptions: NextAuthOptions = {
  secret: process.env.NEXTAUTH_SECRET,
  session: { strategy: "jwt", maxAge: 60 * 60 * 8 },
  providers,
  callbacks: {
    async jwt({ token, account }) {
      if (account?.provider === "demo") {
        token.accessToken = demoAuthBearerToken;
      } else if (account?.access_token) {
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
