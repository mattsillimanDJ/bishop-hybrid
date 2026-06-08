const TOKEN_KEY = "bishop.console.token";
const endpoints = {
  dashboard: "/console/dashboard",
  status: "/console/status",
  projects: "/console/projects",
  nextActions: "/console/next-actions",
  memory: "/console/memory",
  tasks: "/console/tasks",
  conversations: "/console/conversations",
  focus: "/console/focus",
};

const tokenForm = document.querySelector("#token-form");
const tokenInput = document.querySelector("#token-input");
const authPanel = document.querySelector(".auth-panel");
const changeTokenButton = document.querySelector("#change-token");
const clearTokenButton = document.querySelector("#clear-token");
const refreshButton = document.querySelector("#refresh-data");
const authMessage = document.querySelector("#auth-message");
const lastRefreshed = document.querySelector("#last-refreshed");
const taskCaptureForm = document.querySelector("#task-capture-form");
const memoryCaptureForm = document.querySelector("#memory-capture-form");
const focusCaptureForm = document.querySelector("#focus-capture-form");

const sections = {
  dashboard: {
    errorSelector: "#dashboard-error",
    loading: () => {
      setText("#current-focus", "Loading briefing...");
      setText("#current-focus-reason", "Checking active focus and pending work.");
      setText("#current-mode", "Mode: -");
      setText("#current-lane", "Lane: -");
      setText("#current-provider", "Provider: -");
      setText("#today-summary", "Loading today's changes...");
      setText("#today-tasks", "Tasks added today: -");
      setText("#today-conversations", "Conversations logged today: -");
      setText("#today-memory", "Memory added today: -");
      setText("#next-best-action", "Loading next action...");
      setText("#next-best-action-detail", "Looking across tasks and today's changes.");
      setListLoading("#changed-today", "Loading today's changes...");
      setContainerLoading("#attention-projects", "Loading project attention...");
    },
    render: renderDashboard,
  },
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
  nextActions: {
    errorSelector: "#next-actions-error",
    loading: () => setListLoading("#next-actions", "Loading recommended next moves..."),
    render: renderNextActions,
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

function setAuthCollapsed(isCollapsed) {
  authPanel.classList.toggle("authenticated", isCollapsed);
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
  setAuthCollapsed(false);
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

async function postConsole(path, token, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Bishop-Console-Token": token,
    },
    body: JSON.stringify(payload),
  });

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || `${path} returned ${response.status}`);
  }

  return data;
}

function setCaptureMessage(selector, message, isError = false) {
  const node = document.querySelector(selector);
  node.textContent = message;
  node.classList.toggle("error", isError);
  node.classList.toggle("success", Boolean(message) && !isError);
}

async function submitCapture({ form, endpoint, payload, messageSelector, success }) {
  const token = storedToken();
  if (!token) {
    setCaptureMessage(messageSelector, "Paste the Console API token before capturing.", true);
    return;
  }

  const button = form.querySelector("button[type='submit']");
  button.disabled = true;
  setCaptureMessage(messageSelector, "Saving...");

  try {
    const data = await postConsole(endpoint, token, payload);
    setCaptureMessage(messageSelector, success(data));
    await loadConsoleData(token);
  } catch (error) {
    setCaptureMessage(messageSelector, error.message, true);
  } finally {
    button.disabled = false;
  }
}

function itemMeta(parts) {
  return parts.filter(Boolean).join(" | ");
}

function renderStatus(data) {
  clearSectionError("status");
  const counts = data.counts || {};
  const pendingTasks = text(counts.pending_tasks, 0);
  const recentConversations = text(counts.recent_conversations, 0);
  const memoryItems = text(counts.memory, 0);

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
    `${memoryItems} memory | ${pendingTasks} pending | ${recentConversations} conversations`,
  );
}

function renderDashboard(data) {
  clearSectionError("dashboard");
  const focus = data.current_focus || {};
  const summary = data.today_summary || {};
  const action = data.next_best_action || {};

  setText("#current-focus", text(focus.title, "Review the newest task queue."));
  setText("#current-focus-reason", text(focus.reason, "Bishop did not find a pressing focus in Console data."));
  setText("#current-mode", `Mode: ${text(data.mode)}`);
  setText("#current-lane", `Lane: ${text(data.lane)}`);
  setText("#current-provider", `Provider: ${text(data.provider?.effective_provider)}`);

  setText("#today-summary", text(summary.title, "No changes logged today."));
  setText("#today-tasks", `Tasks added today: ${text(summary.tasks_added, 0)}`);
  setText("#today-conversations", `Conversations logged today: ${text(summary.conversations_logged, 0)}`);
  setText("#today-memory", `Memory added today: ${text(summary.memory_added, 0)}`);

  setText("#next-best-action", text(action.title, "Set a concrete focus for Matt's next work block."));
  setText("#next-best-action-detail", text(action.detail, "No pending task is available from Console data."));

  renderList(
    "#changed-today",
    data.changed_today,
    (item) =>
      listItem(
        text(item.title, "Change logged today"),
        itemMeta([text(item.detail), text(item.created_at), "read-only"]),
        "",
      ),
    "No same-day changes found in Console data.",
  );

  renderAttentionProjects(data.attention_projects);
}

function renderAttentionProjects(items) {
  const container = document.querySelector("#attention-projects");
  container.classList.remove("empty");
  container.innerHTML = "";

  if (!items?.length) {
    container.classList.add("empty");
    container.textContent = "No project attention data returned.";
    return;
  }

  for (const project of items) {
    const card = document.createElement("article");
    card.className = "project-card";
    card.innerHTML = `
      <h3></h3>
      <strong class="health"></strong>
      <p></p>
      <p class="meta"></p>
    `;
    card.querySelector("h3").textContent = text(project.name);
    card.querySelector(".health").textContent = text(project.status, "Review");
    card.querySelector("p").textContent = text(project.reason, "");
    card.querySelector(".meta").textContent = itemMeta([
      `${text(project.counts?.pending_tasks, 0)} pending`,
      `${text(project.counts?.today_memory, 0)} memory today`,
      "read-only",
    ]);
    container.append(card);
  }
}

function projectHealth(project) {
  const counts = project.available_counts || {};
  if (counts.task_schema_limited) {
    return "Health: limited task data";
  }
  if ((counts.pending_tasks || 0) > 0) {
    return `Health: active | ${counts.pending_tasks} pending`;
  }
  if ((counts.memory || 0) > 0) {
    return "Health: context ready";
  }
  return "Health: quiet";
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
      <strong class="health"></strong>
      <p></p>
      <p class="meta"></p>
    `;
    card.querySelector("h3").textContent = text(project.name);
    card.querySelector(".health").textContent = projectHealth(project);
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

function renderNextActions(data) {
  clearSectionError("nextActions");
  renderList(
    "#next-actions",
    data.items,
    (item) =>
      listItem(
        text(item.title, "Next move"),
        itemMeta([`lane: ${text(item.lane, "unknown")}`, text(item.created_at), "read-only"]),
        text(item.source_message, ""),
      ),
    "No recommended next moves returned.",
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
    setAuthCollapsed(false);
    setAuthMessage("Missing token. Paste the local CONSOLE_API_TOKEN value to load data.");
    return;
  }

  setAuthCollapsed(false);
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
    setAuthCollapsed(true);
    setAuthMessage("Read-only Console data loaded.");
  } else if (loadedCount > 0) {
    setAuthMessage("Some Console sections could not load. Check section errors.");
  } else {
    setAuthCollapsed(false);
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

changeTokenButton.addEventListener("click", () => {
  setAuthCollapsed(false);
  tokenInput.focus();
  setAuthMessage("Paste a different Console API token, then load again.");
});

refreshButton.addEventListener("click", () => {
  loadConsoleData(storedToken());
});

taskCaptureForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const taskText = document.querySelector("#task-text").value.trim();
  const lane = document.querySelector("#task-lane").value;
  if (!taskText) {
    setCaptureMessage("#task-capture-message", "Task text is required.", true);
    return;
  }

  submitCapture({
    form: taskCaptureForm,
    endpoint: endpoints.tasks,
    payload: { task_text: taskText, lane },
    messageSelector: "#task-capture-message",
    success: (data) => {
      document.querySelector("#task-text").value = "";
      return data.message || "Task captured.";
    },
  });
});

memoryCaptureForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const content = document.querySelector("#memory-content").value.trim();
  const lane = document.querySelector("#memory-lane").value;
  if (!content) {
    setCaptureMessage("#memory-capture-message", "Memory content is required.", true);
    return;
  }

  submitCapture({
    form: memoryCaptureForm,
    endpoint: endpoints.memory,
    payload: { content, lane },
    messageSelector: "#memory-capture-message",
    success: (data) => {
      if (!data.skipped) {
        document.querySelector("#memory-content").value = "";
      }
      return data.message || "Memory captured.";
    },
  });
});

focusCaptureForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const focus = document.querySelector("#focus-value").value;
  if (!focus) {
    setCaptureMessage("#focus-capture-message", "Choose a focus first.", true);
    return;
  }

  submitCapture({
    form: focusCaptureForm,
    endpoint: endpoints.focus,
    payload: { focus },
    messageSelector: "#focus-capture-message",
    success: (data) => data.message || "Focus set.",
  });
});

const initialToken = storedToken();
tokenInput.value = initialToken;
loadConsoleData(initialToken);
