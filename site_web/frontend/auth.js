/**
 * Authentification JWT — partagé entre les pages HTML.
 * Le backend attend l'en-tête : Authorization: Bearer <token>
 */
const API_BASE = typeof window !== "undefined" && window.GPON_API_URL
  ? window.GPON_API_URL
  : "http://localhost:8000";
window.API_BASE = API_BASE;

const TOKEN_KEY = "gpon_access_token";
const USER_KEY = "gpon_user_profile";

function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

function setToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

function clearAuth() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

function authHeaders(includeJson) {
  const h = {};
  const t = getToken();
  if (t) h.Authorization = "Bearer " + t;
  if (includeJson) h["Content-Type"] = "application/json";
  return h;
}

async function fetchMe() {
  const r = await fetch(API_BASE + "/api/auth/me", { headers: authHeaders(false) });
  if (!r.ok) return null;
  const u = await r.json();
  try {
    localStorage.setItem(USER_KEY, JSON.stringify(u));
  } catch (_) {}
  return u;
}

function getStoredUser() {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY) || "null");
  } catch (_) {
    return null;
  }
}

function requireLogin() {
  if (!getToken()) {
    window.location.href = "login.html";
    return false;
  }
  return true;
}

function logout() {
  clearAuth();
  window.location.href = "login.html";
}

window.logout = logout;
window.setToken = setToken;
window.clearAuth = clearAuth;
window.getToken = getToken;
window.authHeaders = authHeaders;
window.fetchMe = fetchMe;
window.getStoredUser = getStoredUser;
window.requireLogin = requireLogin;
