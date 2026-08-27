const form = document.getElementById("authForm");
const formTitle = document.getElementById("formTitle");
const submitBtn = document.getElementById("submitBtn");
const toggleText = document.getElementById("toggleText");
const toggleModeBtn = document.getElementById("toggleModeBtn");
const errorMsg = document.getElementById("errorMsg");

let mode = "login"; // or "signup"
const API = "/api";
// If already logged in, redirect to chat application
// If already logged in, redirect to index
(async () => {
  try {
    const res = await fetch(`${API}/auth/me`, { credentials: "include" });
    if (res.ok) {
      // Redirect to main page without reloading loop
      window.location.replace("/static/index.html");
    }
  } catch (e) {
    // Keep user on login page silently
  }
})();

const usernameInput = document.getElementById("username");

toggleModeBtn.addEventListener("click", () => {
  mode = mode === "login" ? "signup" : "login";
  const isLogin = mode === "login";
  formTitle.textContent = isLogin ? "Log in" : "Sign up";
  submitBtn.textContent = isLogin ? "Log in" : "Sign up";
  toggleText.textContent = isLogin
    ? "Don't have an account?"
    : "Already have an account?";
  toggleModeBtn.textContent = isLogin ? "Sign up" : "Log in";
  errorMsg.classList.add("hidden");

  // Username sirf signup ke waqt chahiye
  usernameInput.classList.toggle("hidden", isLogin);
  usernameInput.required = !isLogin;
});

// Page load pe bhi (default mode "login" hai) — username field hide honi chahiye
usernameInput.classList.add("hidden");
form.addEventListener("submit", async (e) => {
  e.preventDefault();
  errorMsg.classList.add("hidden");
  const email = document.getElementById("email").value.trim();
  const password = document.getElementById("password").value;
  const username = usernameInput.value.trim();

  const endpoint = mode === "login" ? "/auth/login" : "/auth/signup";
  const body =
    mode === "login" ? { email, password } : { username, email, password };

  try {
    const res = await fetch(`${API}${endpoint}`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    const data = await res.json();

    if (!res.ok) {
      if (Array.isArray(data.detail)) {
        throw new Error(data.detail[0].msg);
      }
      throw new Error(data.detail || "Something went wrong.");
    }

    // Token ab httpOnly cookie mein hai (backend ne set kiya) — JS ise
    // chhoo bhi nahi sakti. Sirf non-sensitive display info save karte hain.
    localStorage.setItem("user_email", data.email);
    localStorage.setItem("username", data.username);

    window.location.href = "/static/index.html";
  } catch (err) {
    errorMsg.textContent = err.message;
    errorMsg.classList.remove("hidden");
  }
});
async function handleGoogleSignIn(response) {
  try {
    const res = await fetch(`${API}/auth/google`, {
      method: "POST",
      credentials: "include", // <-- add karein
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id_token: response.credential }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Google sign-in failed.");

    localStorage.setItem("user_email", data.email);
    localStorage.setItem("username", data.username);
    window.location.href = "/static/index.html";
  } catch (err) {
    errorMsg.textContent = err.message;
    errorMsg.classList.remove("hidden");
  }
}
