// --- AUTH GUARD: redirect to login if no token ---
// Guard: httpOnly cookie ko JS check nahi kar sakti, is liye backend
async function checkAuthOrRedirect() {
  try {
    const res = await fetch("/api/auth/me", { credentials: "include" });
    if (!res.ok) {
      window.location.href = "/static/login.html";
      return false;
    }
    return true;
  } catch (e) {
    window.location.href = "/static/login.html";
    return false;
  }
}

// --- Helper: fetch wrapper that always attaches the auth token ---
async function authFetch(url, options = {}) {
  const res = await fetch(url, {
    ...options,
    credentials: "include", // cookie automatically attach hoti hai isse
  });

  if (res.status === 401) {
    localStorage.removeItem("user_email");
    localStorage.removeItem("username");
    window.location.href = "/static/login.html";
    throw new Error("Session expired, redirecting to login.");
  }
  return res;
}

const API = "/api";
let currentChatId = null;
let chats = [];

const chatListEl = document.getElementById("chatList");
const messagesEl = document.getElementById("messages");
const emptyStateEl = document.getElementById("emptyState");
const chatTitleEl = document.getElementById("chatTitle");
const composerEl = document.getElementById("composer");
const inputEl = document.getElementById("messageInput");
const sendBtn = document.getElementById("sendBtn");

// ---------- API calls ----------

async function fetchChats() {
  const res = await authFetch(`${API}/chats`);
  chats = await res.json();
  renderChatList();
}

async function createChat() {
  const res = await authFetch(`${API}/chats`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: "New chat" }),
  });
  const chat = await res.json();
  chats.unshift(chat);
  renderChatList();
  openChat(chat.id);
}

async function openChat(chatId) {
  currentChatId = chatId;
  localStorage.setItem("lastChatId", chatId);
  renderChatList();
  try {
    const res = await authFetch(`${API}/chats/${chatId}`);
    const chat = await res.json();
    chatTitleEl.textContent = chat.title;
    renderMessages(chat.messages || []);
  } catch (error) {
    console.error("Error fetching chat history:", error);
  }
}

function renderMessages(messages) {
  messagesEl.innerHTML = "";
  if (!messages.length) {
    messagesEl.appendChild(emptyStateEl);
    return;
  }
  for (const msg of messages) {
    const messageRowObj = buildMessageRow(msg.role, msg.content);
    messagesEl.appendChild(messageRowObj.row);
  }
  scrollToBottom();
}

async function renameChat(chatId, title) {
  await authFetch(`${API}/chats/${chatId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  await fetchChats();
}

async function deleteChat(chatId) {
  await authFetch(`${API}/chats/${chatId}`, { method: "DELETE" });
  if (currentChatId === chatId) {
    currentChatId = null;
    localStorage.removeItem("lastChatId");
    chatTitleEl.textContent = "Select or start a chat";
    messagesEl.innerHTML = "";
    messagesEl.appendChild(emptyStateEl);
  }
  await fetchChats();
}

async function sendMessage(content) {
  const res = await authFetch(`${API}/chats/${currentChatId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content, top_k: 5 }),
  });
  if (!res.ok) throw new Error("Failed to send message");
  return res.json();
}
document.addEventListener("DOMContentLoaded", () => {
  // LocalStorage se user email ya username fetch karein (jo login par save hua tha)
  const userEmail = localStorage.getItem("user_email") || "User";

  const avatarElement = document.getElementById("userAvatar");
  if (avatarElement && userEmail) {
    // Email/Name ka pehla character nikal kar uppercase karein (e.g. taha@gmail.com -> T)
    const initial = userEmail.charAt(0).toUpperCase();
    avatarElement.textContent = initial;
  }
});
// ---------- Rendering ----------

const CHAT_ITEM_BASE =
  "group flex items-center justify-between px-3 py-2.5 rounded-lg cursor-pointer text-[13.5px] text-cream/70 gap-1.5 border-l-[3px] border-transparent hover:bg-white/10 hover:text-cream transition-colors";
const CHAT_ITEM_ACTIVE = " bg-white/15 text-cream border-gold font-medium";
const CHAT_ITEM_ACTION_BTN =
  "hidden group-hover:inline-flex text-cream/60 hover:text-cream hover:bg-white/15 rounded-md px-1.5 py-1 text-[13px] transition-colors";

function renderChatList() {
  chatListEl.innerHTML = "";
  for (const chat of chats) {
    const item = document.createElement("div");
    item.className =
      CHAT_ITEM_BASE + (chat.id === currentChatId ? CHAT_ITEM_ACTIVE : "");

    const titleSpan = document.createElement("span");
    titleSpan.className =
      "overflow-hidden text-ellipsis whitespace-nowrap flex-1";
    titleSpan.textContent = chat.title;
    titleSpan.onclick = () => openChat(chat.id);

    const actions = document.createElement("div");
    actions.className = "hidden group-hover:flex gap-0.5 flex-shrink-0";

    const renameBtn = document.createElement("button");
    renameBtn.className = CHAT_ITEM_ACTION_BTN;
    renameBtn.textContent = "✎";
    renameBtn.title = "Rename";
    renameBtn.onclick = async (e) => {
      e.stopPropagation();
      const newTitle = prompt("Rename chat:", chat.title);
      if (newTitle && newTitle.trim())
        await renameChat(chat.id, newTitle.trim());
    };

    const deleteBtn = document.createElement("button");
    deleteBtn.className = CHAT_ITEM_ACTION_BTN;
    deleteBtn.textContent = "🗑";
    deleteBtn.title = "Delete";
    deleteBtn.onclick = async (e) => {
      e.stopPropagation();
      if (confirm(`Delete "${chat.title}"?`)) await deleteChat(chat.id);
    };

    actions.append(renameBtn, deleteBtn);
    item.append(titleSpan, actions);
    chatListEl.appendChild(item);
  }
}

const AVATAR_BASE =
  "w-8 h-8 rounded-[9px] flex-shrink-0 flex items-center justify-center text-[12.5px] font-bold font-mono";
const AVATAR_USER = "bg-creamdim text-navy border border-borderline";
const AVATAR_ASSISTANT = "bg-navy text-gold";

const CONTENT_BASE =
  "flex-1 leading-relaxed text-[15px] whitespace-pre-wrap break-words pt-1 text-ink";
const CONTENT_USER_BUBBLE =
  "bg-navy text-cream rounded-tl-[4px] rounded-tr-2xl rounded-br-2xl rounded-bl-2xl px-4.5 py-3 shadow-sm";
const CONTENT_ASSISTANT_RULE = "border-l-[3px] border-gold pl-4";
const CONTENT_LOADING = "italic text-inksoft animate-pulse";

function buildMessageRow(role, content, isLoading = false) {
  const row = document.createElement("div");
  row.className = "py-5 border-b border-borderline animate-message-in";

  const inner = document.createElement("div");
  inner.className = "max-w-[720px] mx-auto px-7 flex gap-4";

  const avatar = document.createElement("div");
  avatar.className = `${AVATAR_BASE} ${role === "user" ? AVATAR_USER : AVATAR_ASSISTANT}`;
  avatar.textContent = role === "user" ? "U" : "A";

  const contentEl = document.createElement("div");
  const roleClass =
    role === "user" ? CONTENT_USER_BUBBLE : CONTENT_ASSISTANT_RULE;
  contentEl.className =
    `${CONTENT_BASE} ${roleClass}` + (isLoading ? ` ${CONTENT_LOADING}` : "");

  if (role === "user") {
    contentEl.textContent = content;
  } else {
    contentEl.innerHTML = marked.parse(content || "");
  }

  inner.append(avatar, contentEl);
  row.appendChild(inner);
  return { row, contentEl };
}

function scrollToBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

// ---------- Composer ----------

composerEl.addEventListener("submit", async (e) => {
  e.preventDefault();
  const content = inputEl.value.trim();
  if (!content) return;

  if (!currentChatId) {
    await createChat();
  }

  inputEl.value = "";
  autoResize();
  sendBtn.disabled = true;

  if (messagesEl.contains(emptyStateEl)) messagesEl.innerHTML = "";

  const { row: userRow } = buildMessageRow("user", content);
  messagesEl.appendChild(userRow);
  scrollToBottom();

  const { row: loadingRow, contentEl: loadingContentEl } = buildMessageRow(
    "assistant",
    "Thinking...",
    true,
  );
  messagesEl.appendChild(loadingRow);
  scrollToBottom();

  try {
    const result = await sendMessage(content);
    loadingContentEl.textContent = result.assistant_message.content;
    loadingContentEl.classList.remove(...CONTENT_LOADING.split(" "));
    await fetchChats();
    if (currentChatId) {
      const chat = chats.find((c) => c.id === currentChatId);
      if (chat) chatTitleEl.textContent = chat.title;
    }
  } catch (err) {
    loadingContentEl.textContent =
      "Something went wrong reaching the assistant.";
    loadingContentEl.classList.remove(...CONTENT_LOADING.split(" "));
    console.error(err);
  } finally {
    sendBtn.disabled = false;
  }
});

inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    composerEl.requestSubmit();
  }
});

inputEl.addEventListener("input", autoResize);
function autoResize() {
  inputEl.style.height = "auto";
  inputEl.style.height = Math.min(inputEl.scrollHeight, 200) + "px";
}

document.getElementById("newChatBtn").addEventListener("click", createChat);

// ---------- Init ----------
document.getElementById("logoutBtn")?.addEventListener("click", () => {
  localStorage.removeItem("access_token");
  localStorage.removeItem("user_email");
  window.location.href = "/static/login.html";
});

// ---------- Account Dropdown + Modal ----------
const userAvatar = document.getElementById("userAvatar");
const userDropdown = document.getElementById("userDropdown");
const accountBtn = document.getElementById("accountBtn");
const accountModal = document.getElementById("accountModal");
const closeAccountModal = document.getElementById("closeAccountModal");
const accountUsername = document.getElementById("accountUsername");
const accountEmail = document.getElementById("accountEmail");
const accountError = document.getElementById("accountError");
const accountSuccess = document.getElementById("accountSuccess");
const saveAccountBtn = document.getElementById("saveAccountBtn");
const logoutBtn = document.getElementById("logoutBtn");

// Toggle dropdown on avatar click
userAvatar.addEventListener("click", (e) => {
  e.stopPropagation();
  userDropdown.classList.toggle("hidden");
});

// Close dropdown when clicking anywhere else
document.addEventListener("click", () => {
  userDropdown.classList.add("hidden");
});

// Open account modal with fresh data from backend
accountBtn.addEventListener("click", async () => {
  userDropdown.classList.add("hidden");
  accountError.classList.add("hidden");
  accountSuccess.classList.add("hidden");

  try {
    const res = await authFetch(`${API}/auth/me`);
    const user = await res.json();
    accountUsername.value = user.username;
    accountEmail.value = user.email;
    accountModal.classList.remove("hidden");
  } catch (err) {
    console.error("Failed to load account info", err);
  }
});

closeAccountModal.addEventListener("click", () => {
  accountModal.classList.add("hidden");
});

saveAccountBtn.addEventListener("click", async () => {
  accountError.classList.add("hidden");
  accountSuccess.classList.add("hidden");

  try {
    const res = await authFetch(`${API}/auth/me`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: accountUsername.value.trim(),
        email: accountEmail.value.trim(),
      }),
    });
    const data = await res.json();

    if (!res.ok) {
      throw new Error(data.detail || "Update failed.");
    }

    localStorage.setItem("username", data.username);
    localStorage.setItem("user_email", data.email);
    updateAvatarLetter();

    accountSuccess.textContent = "Saved successfully!";
    accountSuccess.classList.remove("hidden");
  } catch (err) {
    accountError.textContent = err.message;
    accountError.classList.remove("hidden");
  }
});

logoutBtn.addEventListener("click", async () => {
  try {
    await fetch("/api/auth/logout", { method: "POST", credentials: "include" });
  } catch (e) {
    console.error("Logout request failed", e);
  }
  localStorage.removeItem("user_email");
  localStorage.removeItem("username");
  window.location.href = "/static/login.html";
});

// Sets the avatar letter from the stored username (first letter, uppercase)
function updateAvatarLetter() {
  const username = localStorage.getItem("username");
  userAvatar.textContent = username ? username[0].toUpperCase() : "U";
}
updateAvatarLetter();

// Fixed Init Execution
(async function init() {
  const isAuthed = await checkAuthOrRedirect();
  if (!isAuthed) return; // Immediate halt if unauthenticated

  await fetchChats();
  const savedChatId = localStorage.getItem("lastChatId");
  if (savedChatId && chats.some((c) => c.id === Number(savedChatId))) {
    openChat(Number(savedChatId));
  }
})();
