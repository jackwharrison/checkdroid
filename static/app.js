// ===============================
// IndexedDB helpers
// ===============================

let dbPromise = null;

function openDb() {
  if (!("indexedDB" in window)) {
    console.warn("IndexedDB not supported; offline cache disabled.");
    return Promise.resolve(null);
  }

  if (dbPromise) return dbPromise;

  dbPromise = new Promise((resolve, reject) => {
    const request = indexedDB.open("checkdroid", 3);

    request.onupgradeneeded = (event) => {
      const db = event.target.result;
      if (!db.objectStoreNames.contains("registrations")) {
        const store = db.createObjectStore("registrations", {
          keyPath: "id", // 121 registration id
        });
        store.createIndex("by_program", "programId", { unique: false });
      }
    };

    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });

  return dbPromise;
}

async function saveRegistrations(programId, registrations) {
  const db = await openDb();
  if (!db) return;

  return new Promise((resolve, reject) => {
    const tx = db.transaction("registrations", "readwrite");
    const store = tx.objectStore("registrations");
    const index = store.index("by_program");

    // 1) delete existing records for this program
    const cursorRequest = index.openCursor(IDBKeyRange.only(programId));
    cursorRequest.onsuccess = (event) => {
      const cursor = event.target.result;
      if (cursor) {
        cursor.delete();
        cursor.continue();
      } else {
        // 2) insert new ones
        registrations.forEach((reg) => {
          store.put({ ...reg, programId });
        });
      }
    };

    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

async function loadRegistrations(programId) {
  const db = await openDb();
  if (!db) return [];

  return new Promise((resolve, reject) => {
    const tx = db.transaction("registrations", "readonly");
    const store = tx.objectStore("registrations");
    const index = store.index("by_program");
    const request = index.openCursor(IDBKeyRange.only(programId));

    const result = [];
    request.onsuccess = (event) => {
      const cursor = event.target.result;
      if (cursor) {
        result.push(cursor.value);
        cursor.continue();
      } else {
        resolve(result);
      }
    };
    request.onerror = () => reject(request.error);
  });
}

// ===============================
// Sync logic for program cards
// ===============================

async function syncProgramCard(card, programId) {
  const syncRow = card.querySelector(".sync-row");
  const statusEl = card.querySelector(".sync-status-text");
  const countEl = card.querySelector(".registrations-count");

  // Mark as syncing (for spinner animation)
  if (syncRow) syncRow.classList.add("syncing");
  if (statusEl) statusEl.textContent = "Syncing registrations…";

  // If offline: use cache only
  if (!navigator.onLine) {
    const cached = await loadRegistrations(programId);
    if (countEl) countEl.textContent = cached.length;
    if (statusEl) statusEl.textContent = "Offline – using cached data";
    if (syncRow) syncRow.classList.remove("syncing");
    return;
  }

  try {
    const res = await fetch(`/api/registrations?program_id=${programId}`);
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }
    const data = await res.json();
    const regs = data.registrations || [];

    // Save to offline cache
    await saveRegistrations(programId, regs);

    // Update UI
    if (countEl) countEl.textContent = regs.length;
    if (statusEl) statusEl.textContent = "Fully up-to-date";
  } catch (err) {
    console.error("Sync failed for program", programId, err);

    // Fallback: use whatever we have cached
    const cached = await loadRegistrations(programId);
    if (countEl) countEl.textContent = cached.length;

    if (statusEl) {
      if (cached.length > 0) {
        statusEl.textContent = "Using cached data (sync failed)";
      } else {
        statusEl.textContent = "Sync failed; no cached data";
      }
    }
  } finally {
    if (syncRow) syncRow.classList.remove("syncing");
  }
}

