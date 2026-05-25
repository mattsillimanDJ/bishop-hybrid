const TOKEN_KEY = "bishop.console.token";
const endpoints = {
  status: "/console/status",
  projects: "/console/projects",
  memory: "/console/memory",
  tasks: "/console/tasks",
  conversations: "/console/conversations",
};

const tokenForm = document.querySelector("#token-form");
const tokenInput = document.querySelector("#token-input");
const clearTokenButton = document.querySelector("#clear-token");
const refreshButton = document.querySelector("#refresh-data");
const authMessage = document.querySelector("#auth-message");
const lastRefreshed = document.querySelector("#last-refreshed");

const sections = {
  status: {
    errorSelector: "#status-error",
    loading: () => {
      setText("#app-name", "Loading...");
      setText("#phase", "Loading status");
      setText("#mode-focus", "-");
      setText("#lane", "Lane: -");
      setText("#provider", "-");
      setText("#research", "Research: -");
      setText("#counts", "-");
    },
    render: renderStatus,
  },
  projects: {
    errorSelector: "#projects-error",
    loading: () => setContainerLoading("#projects", "Loading projects..."),
    render: renderProjects,
  },
  memory: {
    errorSelector: "#memory-error",
    loading: () => setListLoading("#memory", "Loading memory..."),
    render: renderMemory,
  },
  tasks: {
    errorSelector: "#tasks-error",
    loading: () => setListLoading("#tasks", "Loading tasks..."),
    render: renderTasks,
  },
  conversations: {
    errorSelector: "#conversations-error",
    loading: () => setListLoading("#conversations", "Loading conversations..."),
    render: renderConversations,
  },
};

function text(value, fallback = "-") {
  if (value === null || value === undefined || value === "") {
    return fallback;
  }
  return String(value);
}

function setText(selector, value) {
  document.querySelector(selector).textContent = value;
}

function setAuthMessage(message) {
  authMessage.textContent = message;
}

function setLastRefreshed(date) {
  lastRefreshed.textContent = `Last refreshed: ${date.toLocaleString()}`;
}

function setRefreshing(isRefreshing) {
  refreshButton.disabled = isRefreshing;
  tokenForm.querySelector("button[type='submit']").disabled = isRefreshing;
}

function setSectionError(name, message) {
  const errorNode = document.querySelector(sections[name].errorSelector);
  errorNode.textContent = message || "";
  errorNode.classList.toggle("visible", Boolean(message));
}

function clearSectionError(name) {
  setSectionError(name, "");
}

function setContainerLoading(selector, message) {
  const container = document.querySelector(selector);
  container.classList.add("empty");
  container.textContent = message;
}

function setListLoading(selector, message) {
  const list = document.querySelector(selector);
  list.classList.add("empty");
  list.innerHTML = "";

  const item = document.createElement("li");
  item.textContent = message;
  list.append(item);
}

function storedToken() {
  return sessionStorage.getItem(TOKEN_KEY) || "";
}

function saveToken(token) {
  sessionStorage.setItem(TOKEN_KEY, token);
}

function clearToken() {
  sessionStorage.removeItem(TOKEN_KEY);
  tokenInput.value = "";
  lastRefreshed.textContent = "Last refreshed: never";
  setAuthMessage("Token cleared. Paste the local Console API token to load data.");
}

async function fetchConsole(path, token) {
  const response = await fetch(path, {
    headers: {
      "X-Bishop-Console-Token": token,
    },
  });

  if (!response.ok) {
    throw new Error(`${path} returned ${response.status}`);
  }

  return response.json();
}

function itemMeta(parts) {
  return parts.filter(Boolean).join(" | ");
}

function renderStatus(data) {
  clearSectionError("status");
  setText("#app-name", text(data.app_name, "Bishop"));
  setText("#phase", `${text(data.console_phase)} | read-only: ${data.read_only === true}`);
  setText("#mode-focus", `${text(data.mode)} / ${text(data.focus)}`);
  setText("#lane", `Lane: ${text(data.lane)}`);
  setText("#provider", text(data.provider?.effective_provider));
  setText(
    "#research",
    `Research: ${text(data.research?.provider)} (${data.research?.configured ? "configured" : "not configured"})`,
  );
  setText(
    "#counts",
    `${text(data.counts?.memory, 0)} memory | ${text(data.counts?.pending_tasks, 0)} pending | ${text(data.counts?.recent_conversations, 0)} conversations`,
  );
}

function renderProjects(data) {
  clearSectionError("projects");
  const container = document.querySelector("#projects");
  container.classList.remove("empty");
  container.innerHTML = "";

  if (!data.items?.length) {
    container.classList.add("empty");
    container.textContent = "No projects returned.";
    return;
  }

  for (const project of data.items) {
    const card = document.createElement("article");
    card.className = "project-card";
    card.innerHTML = `
      <h3></h3>
      <p></p>
      <p class="meta"></p>
    `;
    card.querySelector("h3").textContent = text(project.name);
    card.querySelector("p").textContent = text(project.description, "");
    card.querySelector(".meta").textContent = itemMeta([
      `focus: ${text(project.focus_key)}`,
      `memory: ${text(project.available_counts?.memory, 0)}`,
      `pending: ${text(project.available_counts?.pending_tasks, 0)}`,
      "read-only",
    ]);
    container.append(card);
  }
}

function renderList(selector, items, renderItem, emptyText) {
  const list = document.querySelector(selector);
  list.classList.remove("empty");
  list.innerHTML = "";

  if (!items?.length) {
    list.classList.add("empty");
    const item = document.createElement("li");
    item.textContent = emptyText;
    list.append(item);
    return;
  }

  for (const entry of items) {
    list.append(renderItem(entry));
  }
}

function listItem(title, meta, detail) {
  const item = document.createElement("li");
  const titleNode = document.createElement("span");
  const metaNode = document.createElement("span");
  const detailNode = document.createElement("p");

  titleNode.className = "item-title";
  metaNode.className = "meta";
  titleNode.textContent = title;
  metaNode.textContent = meta;
  detailNode.textContent = detail;

  item.append(titleNode, metaNode, detailNode);
  return item;
}

function renderMemory(data) {
  clearSectionError("memory");
  renderList(
    "#memory",
    data.items,
    (item) =>
      listItem(
        text(item.category, "Memory"),
        itemMeta([text(item.lane), text(item.visibility), text(item.created_at), "read-only"]),
        text(item.content, ""),
      ),
    "No memory returned.",
  );
}

function renderTasks(data) {
  clearSectionError("tasks");
  renderList(
    "#tasks",
    data.items,
    (item) =>
      listItem(
        text(item.task_text || item.text, "Task"),
        itemMeta([text(item.status), text(item.lane), text(item.created_at), "read-only"]),
        text(item.source_message, ""),
      ),
    "No tasks returned.",
  );
}

function renderConversations(data) {
  clearSectionError("conversations");
  renderList(
    "#conversations",
    data.items,
    (item) =>
      listItem(
        text(item.user_message, "Conversation"),
        itemMeta([text(item.mode), text(item.provider), text(item.created_at), "read-only"]),
        text(item.assistant_response, ""),
      ),
    "No conversations returned.",
  );
}

async function loadConsoleData(token) {
  if (!token) {
    setAuthMessage("Missing token. Paste the local CONSOLE_API_TOKEN value to load data.");
    return;
  }

  setAuthMessage("Loading read-only Console data...");
  setRefreshing(true);

  const results = await Promise.all(
    Object.entries(sections).map(async ([name, section]) => {
      section.loading();
      clearSectionError(name);

      try {
        const data = await fetchConsole(endpoints[name], token);
        section.render(data);
        return { name, ok: true };
      } catch (error) {
        setSectionError(name, `Could not load this section. ${error.message}`);
        return { name, ok: false };
      }
    }),
  );

  setRefreshing(false);

  const loadedCount = results.filter((result) => result.ok).length;
  if (loadedCount > 0) {
    setLastRefreshed(new Date());
  }

  if (loadedCount === results.length) {
    setAuthMessage("Read-only Console data loaded.");
  } else if (loadedCount > 0) {
    setAuthMessage("Some Console sections could not load. Check section errors.");
  } else {
    setAuthMessage("Could not load Console data. Check CONSOLE_API_TOKEN and server config.");
  }
}

tokenForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const token = tokenInput.value.trim();
  saveToken(token);
  loadConsoleData(token);
});

clearTokenButton.addEventListener("click", clearToken);

refreshButton.addEventListener("click", () => {
  loadConsoleData(storedToken());
});

const initialToken = storedToken();
tokenInput.value = initialToken;
loadConsoleData(initialToken);
