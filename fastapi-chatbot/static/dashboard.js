// dashboard.js
const API = "/api";

// Verify admin access on load
(async function initDashboard() {
  try {
    const res = await fetch(`${API}/auth/me`, { credentials: "include" });
    if (!res.ok) {
      window.location.href = "/static/login.html";
      return;
    }
    const user = await res.json();
    if (user.role !== "admin") {
      window.location.href = "/static/index.html";
      return;
    }
    fetchUsers();
  } catch (e) {
    window.location.href = "/static/login.html";
  }
})();

async function fetchUsers() {
  const tableBody = document.getElementById("usersTableBody");
  if (!tableBody) return;

  tableBody.innerHTML = `<tr><td colspan="5" class="p-4 text-center text-zinc-500">Loading users...</td></tr>`;

  try {
    const res = await fetch(`${API}/admin/users`, { credentials: "include" });
    if (!res.ok) throw new Error("Failed to load users");
    const users = await res.json();

    tableBody.innerHTML = "";

    if (!Array.isArray(users) || users.length === 0) {
      tableBody.innerHTML = `<tr><td colspan="5" class="p-4 text-center text-zinc-400">No users found.</td></tr>`;
      return;
    }

    users.forEach((u) => {
      const row = document.createElement("tr");
      row.className =
        "hover:bg-[#282a2c] transition-colors border-b border-zinc-800";
      row.innerHTML = `
        <td class="p-4 font-medium">${u.username || "N/A"}</td>
        <td class="p-4 text-zinc-400">${u.email}</td>
        <td class="p-4">
          <span class="px-2.5 py-1 rounded-full text-xs font-semibold ${
            u.role === "admin"
              ? "bg-purple-500/10 text-purple-400 border border-purple-500/20"
              : "bg-blue-500/10 text-blue-400 border border-blue-500/20"
          }">
            ${u.role || "user"}
          </span>
        </td>
        <td class="p-4 text-zinc-400 text-xs">${
          u.created_at ? new Date(u.created_at).toLocaleDateString() : "N/A"
        }</td>
        <td class="p-4">
          <div class="flex items-center gap-2">
            <select id="role-select-${u.id}" class="bg-zinc-800 text-zinc-200 border border-zinc-700 text-xs rounded px-2 py-1 outline-none">
              <option value="user" ${u.role === "user" ? "selected" : ""}>User</option>
              <option value="admin" ${u.role === "admin" ? "selected" : ""}>Admin</option>
            </select>
            <button onclick="updateUserRole(${u.id})" class="bg-purple-600 hover:bg-purple-700 text-white text-xs px-3 py-1 rounded transition-colors">
              Save
            </button>
          </div>
        </td>
      `;
      tableBody.appendChild(row);
    });
  } catch (err) {
    tableBody.innerHTML = `<tr><td colspan="5" class="p-4 text-center text-red-400">${err.message}</td></tr>`;
  }
}

// Function to send PUT request for updating role
async function updateUserRole(userId) {
  const selectEl = document.getElementById(`role-select-${userId}`);
  const newRole = selectEl.value;

  try {
    const res = await fetch(`${API}/admin/users/${userId}/role`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ role: newRole }),
    });

    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed to update role");

    alert(`User role updated to "${newRole}" successfully!`);
    fetchUsers(); // Refresh table
  } catch (err) {
    alert(`Error: ${err.message}`);
  }
}

document
  .getElementById("refreshUsersBtn")
  ?.addEventListener("click", fetchUsers);

document
  .getElementById("adminLogoutBtn")
  ?.addEventListener("click", async () => {
    try {
      await fetch(`${API}/auth/logout`, {
        method: "POST",
        credentials: "include",
      });
    } catch (e) {}
    localStorage.clear();
    window.location.href = "/static/login.html";
  });
