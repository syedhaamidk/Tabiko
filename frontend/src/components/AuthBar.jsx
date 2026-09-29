import { useEffect, useState } from "react";
import { useAuth } from "../AuthContext";
import InterfaceIcon from "./InterfaceIcon";
import GoogleSignIn from "./GoogleSignIn";

const REVIEWER_TYPE_OPTIONS = [
  { value: "normal", label: "Everyday diner", icon: "solo" },
  { value: "food_critic", label: "Food critic", icon: "plate" },
  { value: "cuisine_specialist", label: "Cuisine specialist", icon: "spice" },
];

function ProfileSettings() {
  const { user, updateProfile } = useAuth();
  const [editing, setEditing] = useState(false);
  const [reviewerType, setReviewerType] = useState(user.reviewer_type);
  const [specialty, setSpecialty] = useState(user.cuisine_specialty || "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    setReviewerType(user.reviewer_type);
    setSpecialty(user.cuisine_specialty || "");
  }, [user]);

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      await updateProfile(reviewerType, specialty || null);
      setEditing(false);
    } catch (requestError) {
      setError(requestError.message || "Couldn't update your profile.");
    } finally {
      setSaving(false);
    }
  }

  if (!editing) {
    const type =
      REVIEWER_TYPE_OPTIONS.find((option) => option.value === user.reviewer_type) ||
      REVIEWER_TYPE_OPTIONS[0];
    return (
      <button className="profile-chip" onClick={() => setEditing(true)}>
        <InterfaceIcon name={type.icon} size={16} />
        {type.label}
        {user.reviewer_type === "food_critic" && !user.is_critic_verified && (
          <small>self-identified</small>
        )}
        {user.reviewer_type === "cuisine_specialist" && user.cuisine_specialty && (
          <small>{user.cuisine_specialty}</small>
        )}
      </button>
    );
  }

  return (
    <div className="profile-editor">
      <select
        aria-label="Reviewer type"
        value={reviewerType}
        onChange={(event) => setReviewerType(event.target.value)}
      >
        {REVIEWER_TYPE_OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            <InterfaceIcon name={option.icon} size={15} /> {option.label}
          </option>
        ))}
      </select>
      {reviewerType === "cuisine_specialist" && (
        <input
          aria-label="Cuisine specialty"
          placeholder="e.g. South Indian"
          value={specialty}
          onChange={(event) => setSpecialty(event.target.value)}
        />
      )}
      <button className="app-button app-button--primary" onClick={handleSave} disabled={saving}>
        {saving ? "Saving…" : "Save"}
      </button>
      <button className="app-button app-button--ghost" onClick={() => setEditing(false)}>Cancel</button>
      {error && <span className="auth-error">{error}</span>}
    </div>
  );
}

export default function AuthBar() {
  const { user, login, register, logout } = useAuth();
  const [mode, setMode] = useState(null);
  const [form, setForm] = useState({ name: "", email: "", password: "" });
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      if (mode === "login") {
        await login(form.email, form.password);
      } else {
        await register(form.name, form.email, form.password);
      }
      setMode(null);
      setForm({ name: "", email: "", password: "" });
    } catch (requestError) {
      setError(
        requestError.status === 401
          ? "Incorrect email or password"
          : requestError.message || "Something went wrong",
      );
    } finally {
      setSubmitting(false);
    }
  }

  if (user) {
    return (
      <div className="auth-bar auth-bar--signed-in">
        <span className="auth-avatar" aria-hidden="true">{user.name.slice(0, 1).toUpperCase()}</span>
        <span className="auth-greeting">
          <small>Hey, flavor chaser</small>
          <strong>{user.name}</strong>
        </span>
        <ProfileSettings />
        <button className="app-button app-button--ghost" onClick={logout}>Log out</button>
      </div>
    );
  }

  if (!mode) {
    return (
      <div className="auth-bar auth-bar--guest">
        <span className="auth-bar__note"><InterfaceIcon name="group" size={17} /> Pull up a chair, flavor chaser</span>
        <div className="auth-bar__actions">
          <button className="app-button" onClick={() => setMode("login")}>Log in</button>
          <button className="app-button app-button--primary" onClick={() => setMode("register")}>
            <InterfaceIcon name="sparkles" size={16} /> Sign up free
          </button>
          <GoogleSignIn layout="inline" onDone={() => {}} />
        </div>
      </div>
    );
  }

  return (
    <form className="auth-bar auth-bar--form" onSubmit={handleSubmit}>
      <span className="auth-form-title">
        <InterfaceIcon name={mode === "login" ? "solo" : "group"} size={17} />
        {mode === "login" ? "Good to see you, hungry human" : "Claim your flavor seat"}
      </span>
      {mode === "register" && (
        <input
          aria-label="Name"
          placeholder="Your name"
          value={form.name}
          onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
          required
        />
      )}
      <input
        type="email"
        aria-label="Email"
        placeholder="Email"
        value={form.email}
        onChange={(event) => setForm((current) => ({ ...current, email: event.target.value }))}
        required
      />
      <input
        type="password"
        aria-label="Password"
        placeholder="Password"
        value={form.password}
        onChange={(event) => setForm((current) => ({ ...current, password: event.target.value }))}
        required
        minLength={mode === "register" ? 8 : 1}
      />
      <button className="app-button app-button--primary" type="submit" disabled={submitting}>
        {submitting ? "One sec…" : mode === "login" ? "Log in" : "Create account"}
      </button>
      <button className="app-button app-button--ghost" type="button" onClick={() => setMode(null)}>Cancel</button>
      <GoogleSignIn
        layout="block"
        onDone={() => {
          setMode(null);
          setForm({ name: "", email: "", password: "" });
        }}
      />
      {error && <span className="auth-error">{error}</span>}
    </form>
  );
}
