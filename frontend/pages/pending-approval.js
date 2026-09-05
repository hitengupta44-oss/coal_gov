import { useAuth } from "../lib/useAuth";

export default function PendingApproval() {
  const { user, logout } = useAuth();

  return (
    <div style={{ maxWidth: 500, margin: "80px auto", fontFamily: "sans-serif", textAlign: "center" }}>
      <h1>Account Pending Setup</h1>
      <p>
        You're logged in as <strong>{user?.email}</strong>, but no role has
        been assigned to your account yet.
      </p>
      <p style={{ color: "#666", fontSize: 14 }}>
        Ask your admin to add a row for you in the <code>user_profiles</code> table
        (Supabase Table Editor) with your Firebase UID: <code>{user?.uid}</code>
      </p>
      <button onClick={logout}>Log Out</button>
    </div>
  );
}
