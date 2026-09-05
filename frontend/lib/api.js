// Calls the Gradio backend (deployed on Hugging Face Spaces).
// Gradio's REST convention: POST to /run/<function_name> with
// { "data": [arg1, arg2, ...] } in the same order as the Python function args.
//
// SECURITY UPDATE: every function below now takes idToken as its FIRST
// argument, matching backend/app.py's _authenticate(id_token) on every
// endpoint. Get the token from useAuth()'s getIdToken() right before
// calling -- it's a fresh JWT each time (cheap, auto-refreshed by the
// Firebase SDK), don't cache it yourself.

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL; // e.g. https://yourname-coal-backend.hf.space

async function callBackend(fnName, args = []) {
  const res = await fetch(`${BACKEND_URL}/run/${fnName}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ data: args }),
  });
  if (!res.ok) throw new Error(`Backend call failed: ${fnName} (${res.status})`);
  const json = await res.json();
  return json.data ? json.data[0] : json;
}

export const getDashboardSummary = (idToken, subsidiaryFilter = "All") =>
  callBackend("get_dashboard_summary", [idToken, subsidiaryFilter]);

export const getHighRiskMines = (idToken, limit = 10) =>
  callBackend("get_high_risk_mines", [idToken, limit]);

// NOTE: inspectorId is no longer sent -- the backend derives the inspector's
// identity from their own verified idToken (see log_field_inspection's
// SECURITY FIX comment in app.py), so a caller can't log an inspection
// under someone else's name.
export const logFieldInspection = (idToken, payload) =>
  callBackend("log_field_inspection", [
    idToken,
    payload.mineId,
    payload.latitude,
    payload.longitude,
    payload.observationType,
    payload.severity,
    payload.notes || "",
  ]);

export const getComplianceStatus = (idToken, mineId) =>
  callBackend("get_compliance_status", [idToken, mineId]);

// NOTE: actorUid is no longer sent -- the backend logs the audit entry
// using the uid derived from idToken, which is more trustworthy than a
// client-supplied value anyway.
export const updateComplianceStatus = (idToken, trackingId, newStatus, remarks = "") =>
  callBackend("update_compliance_status", [idToken, trackingId, newStatus, remarks]);

export const chatWithAssistant = (idToken, message, history = []) =>
  callBackend("chat_with_data_assistant", [idToken, message, history]);

// Admin-only. Real gating is now the caller's OWN Firebase-verified role
// being 'admin' (checked server-side against user_profiles) -- adminKey is
// just an optional second factor on top, only enforced if ADMIN_SECRET_KEY
// is set in the backend's secrets. Pass "" if you haven't set one.
export const listPendingSignups = (idToken, adminKey = "") =>
  callBackend("list_pending_signups", [idToken, adminKey]);

export const approveUserRole = (idToken, adminKey, payload) =>
  callBackend("approve_user_role", [
    idToken,
    adminKey,
    payload.firebaseUid,
    payload.email,
    payload.fullName || "",
    payload.role,
    payload.mineId || "",
    payload.subsidiaryId || "",
  ]);
