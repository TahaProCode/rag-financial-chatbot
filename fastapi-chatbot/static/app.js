// --- AUTH GUARD: redirect to login if no token ---
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

async function authFetch(url, options = {}) {
  const res = await fetch(url, {
    ...options,
    credentials: "include",
  });

  if (res.status === 401) {
    localStorage.clear();
    window.location.href = "/static/login.html";
    throw new Error("Session expired, redirecting to login.");
  }
  return res;
}

const API = "/api";
let currentChatId = null;
let chats = [];

// DOM Elements
const chatListEl = document.getElementById("chatList");
const messagesEl = document.getElementById("messages");
const emptyStateEl = document.getElementById("emptyState");
const chatTitleEl = document.getElementById("chatTitle");
const composerEl = document.getElementById("composer");
const inputEl = document.getElementById("messageInput");
const sendBtn = document.getElementById("sendBtn");

// ADDED: File Upload DOM Elements
const attachFileBtn = document.getElementById("attachFileBtn");
const fileInput = document.getElementById("fileInput");
const filePreviewContainer = document.getElementById("filePreviewContainer");
const filePreviewName = document.getElementById("filePreviewName");
const removeFileBtn = document.getElementById("removeFileBtn");

let currentFile = null; // Store selected file

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
  clearFileSelection(); // Clear pending file if switching chats
  try {
    const res = await authFetch(`${API}/chats/${chatId}`);
    const chat = await res.json();
    chatTitleEl.textContent = chat.title;
    renderMessages(chat.messages || []);
  } catch (error) {
    console.error("Error fetching chat history:", error);
  }
}

// UPDATED: Render message to show attachment chip if present
function renderMessages(messages) {
  messagesEl.innerHTML = "";
  if (!messages.length) {
    messagesEl.appendChild(emptyStateEl);
    return;
  }
  for (const msg of messages) {
    // Pass file_path if it exists in history
    const messageRowObj = buildMessageRow(
      msg.role,
      msg.content,
      false,
      msg.file_path,
    );
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

// UPDATED: Send message as FormData if file exists, else JSON
async function sendMessage(content, file) {
  const formData = new FormData();
  formData.append("content", content);
  formData.append("top_k", 5);

  // Agar file select hui ho tabhi append karein
  if (file) {
    formData.append("file", file);
  }

  // Hamesha FormData hi bhejein (Content-Type header set mat karein)
  const res = await authFetch(`${API}/chats/${currentChatId}/messages`, {
    method: "POST",
    body: formData,
  });

  if (!res.ok) throw new Error("Failed to send message");
  return res.json();
}

document.addEventListener("DOMContentLoaded", () => {
  const userEmail = localStorage.getItem("user_email") || "User";
  const avatarElement = document.getElementById("userAvatar");
  if (avatarElement && userEmail) {
    avatarElement.textContent = userEmail.charAt(0).toUpperCase();
  }
  const role = localStorage.getItem("user_role");
  const adminBtn = document.getElementById("adminDashboardBtn");
  if (role === "admin" && adminBtn) {
    adminBtn.classList.remove("hidden");
  }
});

// ---------- File Handling UI Logic ----------

attachFileBtn.addEventListener("click", () => {
  fileInput.click();
});

fileInput.addEventListener("change", (e) => {
  if (e.target.files && e.target.files.length > 0) {
    currentFile = e.target.files[0];
    filePreviewName.textContent = currentFile.name;
    filePreviewContainer.classList.remove("hidden");
  }
});

removeFileBtn.addEventListener("click", clearFileSelection);

function clearFileSelection() {
  currentFile = null;
  fileInput.value = "";
  filePreviewContainer.classList.add("hidden");
}

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
    renameBtn.onclick = async (e) => {
      e.stopPropagation();
      const newTitle = prompt("Rename chat:", chat.title);
      if (newTitle && newTitle.trim())
        await renameChat(chat.id, newTitle.trim());
    };

    const deleteBtn = document.createElement("button");
    deleteBtn.className = CHAT_ITEM_ACTION_BTN;
    deleteBtn.textContent = "🗑";
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
  "flex-1 leading-relaxed text-[15px] whitespace-pre-wrap break-words pt-1 text-ink flex flex-col gap-2";
const CONTENT_USER_BUBBLE =
  "bg-navy text-cream rounded-tl-[4px] rounded-tr-2xl rounded-br-2xl rounded-bl-2xl px-4.5 py-3 shadow-sm";
const CONTENT_ASSISTANT_RULE = "border-l-[3px] border-gold pl-4";
const CONTENT_LOADING = "italic text-inksoft animate-pulse";

// UPDATED: buildMessageRow now accepts filePath to render an attachment chip
function buildMessageRow(role, content, isLoading = false, filePath = null) {
  const row = document.createElement("div");
  row.className = "py-5 border-b border-borderline animate-message-in";

  const inner = document.createElement("div");
  inner.className = "max-w-[720px] mx-auto px-7 flex gap-4";

  const avatar = document.createElement("div");
  avatar.className = `${AVATAR_BASE} ${role === "user" ? AVATAR_USER : AVATAR_ASSISTANT}`;
  avatar.textContent = role === "user" ? "U" : "A";

  const contentContainer = document.createElement("div");
  const roleClass =
    role === "user" ? CONTENT_USER_BUBBLE : CONTENT_ASSISTANT_RULE;
  contentContainer.className =
    `${CONTENT_BASE} ${roleClass}` + (isLoading ? ` ${CONTENT_LOADING}` : "");

  // Add File Attachment Chip if it exists
  if (filePath) {
    const fileName = filePath.split("/").pop().split("\\").pop(); // extract filename
    const fileChip = document.createElement("div");
    fileChip.className =
      "flex items-center gap-1.5 bg-[#2d2f31] border border-[#37393b] rounded text-xs px-2 py-1 w-fit mt-1";
    fileChip.innerHTML = `<span class="material-icons-outlined text-[14px] text-[#4285f4]">insert_drive_file</span><span class="truncate max-w-[200px]">${fileName}</span>`;
    contentContainer.appendChild(fileChip);
  }

  const textEl = document.createElement("div");
  if (role === "user") {
    textEl.textContent = content;
  } else {
    textEl.innerHTML = marked.parse(content || "");
  }
  contentContainer.appendChild(textEl);

  inner.append(avatar, contentContainer);
  row.appendChild(inner);
  return { row, contentEl: textEl }; // return textEl for updating loading state
}

function scrollToBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

// ---------- Composer ----------

// UPDATED: Submit handler passes currentFile
composerEl.addEventListener("submit", async (e) => {
  e.preventDefault();
  const content = inputEl.value.trim();
  if (!content && !currentFile) return; // Allow empty text if file is attached

  if (!currentChatId) {
    await createChat();
  }

  const fileToSend = currentFile; // Store reference before clearing UI
  const textToSend = content || "Attached a file for analysis."; // Fallback text

  inputEl.value = "";
  autoResize();
  clearFileSelection(); // Clear UI immediately after submitting
  sendBtn.disabled = true;

  if (messagesEl.contains(emptyStateEl)) messagesEl.innerHTML = "";

  // Render user message with mock file path just for UI display
  const tempFilePath = fileToSend ? fileToSend.name : null;
  const { row: userRow } = buildMessageRow(
    "user",
    textToSend,
    false,
    tempFilePath,
  );
  messagesEl.appendChild(userRow);
  scrollToBottom();

  const { row: loadingRow, contentEl: loadingContentEl } = buildMessageRow(
    "assistant",
    "Analyzing...",
    true,
  );
  messagesEl.appendChild(loadingRow);
  scrollToBottom();

  try {
    const result = await sendMessage(textToSend, fileToSend);
    loadingContentEl.innerHTML = marked.parse(
      result.assistant_message.content || "",
    );
    loadingContentEl.parentElement.classList.remove(
      ...CONTENT_LOADING.split(" "),
    );
    await fetchChats();
    if (currentChatId) {
      const chat = chats.find((c) => c.id === currentChatId);
      if (chat) chatTitleEl.textContent = chat.title;
    }
  } catch (err) {
    loadingContentEl.textContent =
      "Something went wrong reaching the assistant.";
    loadingContentEl.parentElement.classList.remove(
      ...CONTENT_LOADING.split(" "),
    );
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
const logoutBtn = document.getElementById("logoutBtn"); // Main sidebar logout
const sidebarLogoutBtn = document.getElementById("sidebarLogoutBtn"); // Dropdown logout

userAvatar.addEventListener("click", (e) => {
  e.stopPropagation();
  userDropdown.classList.toggle("hidden");
});

document.addEventListener("click", () => {
  userDropdown.classList.add("hidden");
});

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

    if (!res.ok) throw new Error(data.detail || "Update failed.");

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

async function handleLogout() {
  try {
    await fetch("/api/auth/logout", { method: "POST", credentials: "include" });
  } catch (e) {
    console.error("Logout request failed", e);
  }
  localStorage.clear();
  window.location.href = "/static/login.html";
}

logoutBtn.addEventListener("click", handleLogout);
if (sidebarLogoutBtn) sidebarLogoutBtn.addEventListener("click", handleLogout);

function updateAvatarLetter() {
  const username = localStorage.getItem("username");
  if (userAvatar && username)
    userAvatar.textContent = username[0].toUpperCase();
}
updateAvatarLetter();

(async function init() {
  const isAuthed = await checkAuthOrRedirect();
  if (!isAuthed) return;

  await fetchChats();
  const savedChatId = localStorage.getItem("lastChatId");
  if (savedChatId && chats.some((c) => c.id === Number(savedChatId))) {
    openChat(Number(savedChatId));
  }
})();
