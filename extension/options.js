const DEFAULTS = {
  apiUrl: "http://localhost:8000",
  extensionToken: "",
  initialHistoryDays: 7,
  fallbackEmail: "",
};

const fields = {
  apiUrl: document.getElementById("apiUrl"),
  extensionToken: document.getElementById("extensionToken"),
  initialHistoryDays: document.getElementById("initialHistoryDays"),
  fallbackEmail: document.getElementById("fallbackEmail"),
};

const statusEl = document.getElementById("status");

async function load() {
  const config = await chrome.storage.local.get(DEFAULTS);
  for (const [key, input] of Object.entries(fields)) {
    input.value = config[key] ?? DEFAULTS[key];
  }

  const managed = await chrome.storage.managed.get(null).catch(() => ({}));
  for (const [key, value] of Object.entries(managed)) {
    if (fields[key] && value !== undefined) {
      fields[key].value = value;
      fields[key].disabled = true;
    }
  }

  const state = await chrome.storage.local.get([
    "lastSuccessfulSync",
    "lastSyncResult",
    "lastSyncError",
    "initialSyncCompleted",
  ]);

  statusEl.textContent = JSON.stringify(state, null, 2);
}

async function save() {
  await chrome.storage.local.set({
    apiUrl: fields.apiUrl.value.trim(),
    extensionToken: fields.extensionToken.value.trim(),
    initialHistoryDays: Number(fields.initialHistoryDays.value || 7),
    fallbackEmail: fields.fallbackEmail.value.trim(),
  });
  statusEl.textContent = "Saved.";
}

document.getElementById("save").addEventListener("click", async () => {
  await save();
});

document.getElementById("test").addEventListener("click", async () => {
  await save();
  statusEl.textContent = "Testing...";
  const result = await chrome.runtime.sendMessage({ type: "TEST_SYNC" });
  statusEl.textContent = JSON.stringify(result, null, 2);
});

document.getElementById("initial").addEventListener("click", async () => {
  await save();
  statusEl.textContent = "Running initial sync...";
  const result = await chrome.runtime.sendMessage({ type: "INITIAL_SYNC" });
  statusEl.textContent = JSON.stringify(result, null, 2);
});

void load();
