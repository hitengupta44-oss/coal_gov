// Calls the Gradio backend (deployed on Hugging Face Spaces).
// Gradio's REST convention: POST to /run/<function_name> with
// { "data": [arg1, arg2, ...] } in the same order as the Python function args.

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

export const getDashboardSummary = (subsidiaryFilter = "All") =>
  callBackend("get_dashboard_summary", [subsidiaryFilter]);

export const getHighRiskMines = (limit = 10) =>
  callBackend("get_high_risk_mines", [limit]);

export const logFieldInspection = (payload) =>
  callBackend("log_field_inspection", [
    payload.mineId,
    payload.inspectorId,
    payload.latitude,
    payload.longitude,
    payload.observationType,
    payload.severity,
    payload.notes || "",
  ]);

export const getComplianceStatus = (mineId) =>
  callBackend("get_compliance_status", [mineId]);

export const updateComplianceStatus = (trackingId, newStatus, remarks = "", actorUid = "") =>
  callBackend("update_compliance_status", [trackingId, newStatus, remarks, actorUid]);

export const chatWithAssistant = (message, history = []) =>
  callBackend("chat_with_data_assistant", [message, history]);

// Admin-only -- both require adminKey, checked server-side against
// ADMIN_SECRET_KEY. See the SECURITY NOTE in backend/app.py above these
// two functions for why this is a shared-secret stopgap, not real auth.
export const listPendingSignups = (adminKey) =>
  callBackend("list_pending_signups", [adminKey]);

export const approveUserRole = (adminKey, payload) =>
  callBackend("approve_user_role", [
    adminKey,
    payload.firebaseUid,
    payload.email,
    payload.fullName || "",
    payload.role,
    payload.mineId || "",
    payload.subsidiaryId || "",
  ]);