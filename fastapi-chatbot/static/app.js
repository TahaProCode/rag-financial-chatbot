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
  const res = await fetch(`${API}/chats`);
  chats = await res.json();
  renderChatList();
}

async function createChat() {
  const res = await fetch(`${API}/chats`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: "New chat" }),
  });
  const chat = await res.json();
  chats.unshift(chat);
  renderChatList();
  openChat(chat.id);
}
// Nayi chat banane ke liye yeh server ko POST request bhejta hai jiska default title "New chat" hota hai.
// Jab server nayi chat bana deta hai, toh chats.unshift(chat) ke zariye use list me sab se upar (shuru me) add kar diya
// jata hai. Phir screen update hoti hai aur woh chat automatically openChat() ke zariye khul jati hai
async function openChat(chatId) {
  currentChatId = chatId;
  localStorage.setItem("lastChatId", chatId);
  renderChatList();
  try {
    const res = await fetch(`${API}/chats/${chatId}`);
    const chat = await res.json();
    console.log("Fetched Chat Data on Refresh:", chat); // <--- Yeh log lagayein aur Browser Console check karein
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
    // .row lagane se sirf HTML div element append hoga
    const messageRowObj = buildMessageRow(msg.role, msg.content);
    messagesEl.appendChild(messageRowObj.row);
  }
  scrollToBottom();
}
async function renameChat(chatId, title) {
  await fetch(`${API}/chats/${chatId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  await fetchChats();
}

async function deleteChat(chatId) {
  await fetch(`${API}/chats/${chatId}`, { method: "DELETE" });
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
  const res = await fetch(`${API}/chats/${currentChatId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content, top_k: 5 }),
  });
  if (!res.ok) throw new Error("Failed to send message");
  return res.json();
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
  contentEl.textContent = content;

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

  // Optimistically show the user's message
  const { row: userRow } = buildMessageRow("user", content);
  messagesEl.appendChild(userRow);
  scrollToBottom();

  // Placeholder "thinking" bubble for the assistant
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
    await fetchChats(); // refresh sidebar (title / ordering may have changed)
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
(async function init() {
  await fetchChats();
  const savedChatId = localStorage.getItem("lastChatId");
  if (savedChatId && chats.some((c) => c.id === Number(savedChatId))) {
    openChat(Number(savedChatId));
  }
})();
