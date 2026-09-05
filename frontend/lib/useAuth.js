import { useEffect, useState, createContext, useContext } from "react";
import { onAuthStateChanged, signInWithEmailAndPassword, createUserWithEmailAndPassword, updateProfile, signOut } from "firebase/auth";
import { auth } from "./firebase";
import { supabase } from "./supabase";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);       // Firebase user object
  const [profile, setProfile] = useState(null); // Supabase user_profiles row (has role, mine_id, subsidiary_id)
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const unsub = onAuthStateChanged(auth, async (u) => {
      setUser(u);
      if (u) {
        const { data, error } = await supabase
          .from("user_profiles")
          .select("*")
          .eq("firebase_uid", u.uid)
          .single();

        if (error) {
          // No profile row yet -- this account hasn't been assigned a role.
          // In production, gate this behind an admin-approval flow instead
          // of leaving it null.
          setProfile(null);
        } else {
          setProfile(data);
        }
      } else {
        setProfile(null);
      }
      setLoading(false);
    });
    return unsub;
  }, []);

  const login = (email, password) => signInWithEmailAndPassword(auth, email, password);
  // New: self-service signup. Creates the Firebase Auth account only --
  // there is deliberately no user_profiles row yet, so dashboard/index.js
  // will route this person to /pending-approval until an admin assigns
  // them a role via /dashboard/admin. fullName is stored as the Firebase
  // displayName so it shows up as a pre-filled hint in the admin's
  // approval table (see admin.js's use of user.display_name).
  const signup = async (email, password, fullName) => {
    const cred = await createUserWithEmailAndPassword(auth, email, password);
    if (fullName) {
      await updateProfile(cred.user, { displayName: fullName });
    }
    return cred;
  };
  const logout = () => signOut(auth);
  // Every backend call now needs a fresh Firebase ID token (see backend/app.py's
  // _authenticate()). getIdToken() caches internally and auto-refreshes near
  // expiry, so it's cheap to call before every request.
  const getIdToken = () => (user ? user.getIdToken() : Promise.resolve(null));

  return (
    <AuthContext.Provider value={{ user, profile, loading, login, signup, logout, getIdToken }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
