import { useEffect, useState, createContext, useContext } from "react";
import { onAuthStateChanged, signInWithEmailAndPassword, signOut } from "firebase/auth";
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
  const logout = () => signOut(auth);

  return (
    <AuthContext.Provider value={{ user, profile, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
