(function () {
  let jobStatusTimer = null;

  function loadImage(img, refresh) {
    if (!img || img.dataset.loaded === "1") return;
    const base = img.dataset.snapshotSrc;
    if (!base) return;
    const separator = base.includes("?") ? "&" : "?";
    img.src = refresh ? `${base}${separator}refresh=1&t=${Date.now()}` : base;
    img.dataset.loaded = "1";
    img.addEventListener(
      "error",
      () => {
        img.classList.add("failed");
      },
      { once: true }
    );
  }

  function loadSnapshotsIn(root, refresh) {
    root.querySelectorAll("img[data-snapshot-src]").forEach((img) => {
      if (refresh) {
        img.dataset.loaded = "0";
        img.classList.remove("failed");
      }
      loadImage(img, refresh);
    });
  }

  function setView(root, view, storageKey, persist) {
    root.querySelectorAll("[data-camera-view]").forEach((panel) => {
      const active = panel.dataset.cameraView === view;
      panel.hidden = !active;
      if (active && view === "grid") loadSnapshotsIn(panel, false);
    });

    document.querySelectorAll(`[data-camera-view-toggle][data-storage-key="${storageKey}"]`).forEach((toggle) => {
      toggle.querySelectorAll("[data-view-choice]").forEach((button) => {
        const active = button.dataset.viewChoice === view;
        button.classList.toggle("active", active);
        button.setAttribute("aria-pressed", active ? "true" : "false");
      });
    });

    localStorage.setItem(storageKey, view);

    // Persist to server when triggered by user interaction (not initial load)
    if (persist !== false) {
      const prefKey = storageKey === "blink.camerasView" ? "camera_view"
                    : storageKey === "blink.cameraPickerView" ? "camera_picker_view"
                    : null;
      if (prefKey) {
        fetch("/api/prefs", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ key: prefKey, value: view }),
        }).catch(() => {});
      }
    }
  }

  function setupRoot(root) {
    const toggle = root.closest("main").querySelector("[data-camera-view-toggle]");
    const storageKey = toggle ? toggle.dataset.storageKey : "blink.cameraView";
    // Prefer server-persisted value (data-initial-view) over localStorage
    const serverView = toggle ? toggle.dataset.initialView : null;
    const saved = serverView || localStorage.getItem(storageKey) || "list";
    setView(root, saved === "grid" ? "grid" : "list", storageKey, false);

    if (toggle) {
      toggle.querySelectorAll("[data-view-choice]").forEach((button) => {
        button.addEventListener("click", () => setView(root, button.dataset.viewChoice, storageKey));
      });
    }

    root.querySelectorAll(".camera-name-preview").forEach((preview) => {
      preview.addEventListener("mouseenter", () => loadSnapshotsIn(preview, false), { passive: true });
      preview.addEventListener("focusin", () => loadSnapshotsIn(preview, false));
    });
    setupCameraFilters(root);
  }

  function setupCameraFilters(root) {
    if (root.dataset.cameraFiltersBound === "1") {
      applyCameraFilters(root);
      return;
    }
    root.dataset.cameraFiltersBound = "1";
    root.querySelectorAll("[data-camera-search], [data-console-filter]").forEach((control) => {
      control.addEventListener("input", () => applyCameraFilters(root));
      control.addEventListener("change", () => applyCameraFilters(root));
    });
    applyCameraFilters(root);
  }

  function applyCameraFilters(root) {
    const query = (root.querySelector("[data-camera-search]")?.value || "").trim().toLowerCase();
    const consoleFilters = Array.from(root.querySelectorAll("[data-console-filter]"));
    const activeConsoleIds = new Set(consoleFilters.filter((input) => input.checked).map((input) => input.value));
    const useConsoleFilter = consoleFilters.length > 0;
    root.querySelectorAll("[data-camera-item]").forEach((item) => {
      const name = item.dataset.cameraName || "";
      const consoleId = item.dataset.consoleId || "";
      const matchesName = !query || name.includes(query);
      const matchesConsole = !useConsoleFilter || activeConsoleIds.has(consoleId);
      item.hidden = !(matchesName && matchesConsole);
    });
  }

  document.addEventListener("change", (event) => {
    const input = event.target;
    if (!(input instanceof HTMLInputElement)) return;
    if (input.name !== "camera_ids") return;
    input.closest(".camera-picker-card")?.classList.toggle("selected", input.checked);
    input.closest(".camera-picker-row")?.classList.toggle("selected", input.checked);
  });

  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-refresh-snapshots]");
    if (!button) return;
    document.querySelectorAll("[data-camera-view-root]").forEach((root) => loadSnapshotsIn(root, true));
  });

  document.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-reveal-job]");
    if (!button) return;
    const status = document.querySelector("[data-reveal-status]");
    try {
      const response = await fetch(button.dataset.revealUrl, { headers: { Accept: "application/json" } });
      const data = await response.json();
      if (!response.ok || !data.path) throw new Error(data.error || "Could not locate the MP4.");
      const api = window.pywebview && window.pywebview.api;
      if (api && typeof api.reveal_path === "function") {
        await api.reveal_path(data.path);
        if (status) status.textContent = `Revealed ${data.name} in Finder.`;
      } else if (status) {
        status.textContent = `Saved at ${data.path}`;
      }
    } catch (error) {
      if (status) status.textContent = error.message || "Could not reveal this file.";
    }
  });

  document.addEventListener("click", (event) => {
    if (event.target.closest("[data-open-video-modal]")) {
      const modal = document.querySelector("[data-video-modal]");
      if (modal) modal.hidden = false;
    }
    if (event.target.closest("[data-close-video-modal]") || event.target.matches("[data-video-modal]")) {
      closeVideoModal();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeVideoModal();
  });

  function initializePage() {
    document.querySelectorAll("[data-camera-view-root]").forEach(setupRoot);
    setupDailyWindowControls();
    setupEarliestAvailableControls();
    setupOutputScaleControls();
    setupFrameHoldPreview();
    setupEstimatedLength();
    setupSetupControls();
    startJobStatusPolling();
    startNavBadgePoll();
  }

  function startNavBadgePoll() {
    const badge = document.getElementById("nav-jobs-badge");
    if (!badge) return;
    async function tick() {
      try {
        const r = await fetch("/api/jobs/active-count", { headers: { Accept: "application/json" } });
        const { count } = await r.json();
        badge.textContent = count;
        badge.hidden = count === 0;
      } catch (_) {}
    }
    tick();
    if (!window._navBadgeInterval) {
      window._navBadgeInterval = setInterval(tick, 4000);
    }
  }

  function setupEstimatedLength() {
    const display = document.querySelector("[data-estimated-length]");
    const text = document.querySelector("[data-estimated-length-text]");
    if (!display || !text) return;

    function compute() {
      const earliest = document.querySelector("[data-toggle-earliest-available]")?.checked;
      const startVal = document.querySelector('[name="start_at"]')?.value;
      const endVal = document.querySelector('[name="end_at"]')?.value;

      if (earliest) {
        text.textContent = "Estimated length: unavailable (earliest available start date unknown)";
        display.hidden = false;
        return;
      }
      if (!startVal || !endVal) {
        display.hidden = true;
        return;
      }

      const start = new Date(startVal);
      const end = new Date(endVal);
      if (end < start) {
        display.hidden = true;
        return;
      }

      const numDays = Math.round((end - start) / 86_400_000) + 1;

      const dailyEnabled = document.querySelector('[name="daily_window_enabled"]')?.checked;
      let windowSeconds;
      if (dailyEnabled) {
        const ds = document.querySelector('[name="daily_start"]')?.value;
        const de = document.querySelector('[name="daily_end"]')?.value;
        if (!ds || !de) {
          display.hidden = true;
          return;
        }
        const [sh, sm] = ds.split(":").map(Number);
        const [eh, em] = de.split(":").map(Number);
        windowSeconds = (eh * 60 + em - (sh * 60 + sm)) * 60;
        if (windowSeconds <= 0) {
          display.hidden = true;
          return;
        }
      } else {
        windowSeconds = 86_400;
      }

      const amount = Math.max(1, parseInt(document.querySelector("[data-interval-amount]")?.value || "1", 10));
      const unit = document.querySelector("[data-interval-unit]")?.value || "minute";
      const unitSeconds = { second: 1, minute: 60, hour: 3600, day: 86_400 };
      const intervalSec = amount * (unitSeconds[unit] ?? 60);
      if (intervalSec <= 0) {
        display.hidden = true;
        return;
      }

      const fps = Math.max(1, parseInt(document.querySelector("[data-output-fps]")?.value || "30", 10));
      const repeat = Math.max(1, parseInt(document.querySelector("[data-frame-repeat]")?.value || "1", 10));

      const totalFrames = (numDays * windowSeconds / intervalSec) * repeat;
      const videoSeconds = totalFrames / fps;

      const h = Math.floor(videoSeconds / 3600);
      const m = Math.floor((videoSeconds % 3600) / 60);
      const s = Math.floor(videoSeconds % 60);
      const hms = [h, m, s].map((n) => String(n).padStart(2, "0")).join(":");

      text.textContent = `Estimated video: ${hms}  (${Math.round(totalFrames).toLocaleString()} output frames, assuming full availability)`;
      display.hidden = false;
    }

    const selectors = [
      '[name="start_at"]',
      '[name="end_at"]',
      "[data-toggle-earliest-available]",
      '[name="daily_window_enabled"]',
      '[name="daily_start"]',
      '[name="daily_end"]',
      "[data-interval-amount]",
      "[data-interval-unit]",
      "[data-output-fps]",
      "[data-frame-repeat]",
    ];
    selectors.forEach((sel) => {
      document.querySelector(sel)?.addEventListener("input", compute);
      document.querySelector(sel)?.addEventListener("change", compute);
    });
    compute();
  }

  function setupFrameHoldPreview() {
    const repeatInput = document.querySelector("[data-frame-repeat]");
    const fpsInput = document.querySelector("[data-output-fps]");
    const preview = document.querySelector("[data-frame-hold-preview]");
    if (!repeatInput || !preview) return;

    function update() {
      const repeat = Math.max(1, parseInt(repeatInput.value, 10) || 1);
      const fps = Math.max(1, parseInt(fpsInput ? fpsInput.value : "30", 10) || 30);
      const secs = repeat / fps;
      preview.textContent = `= ${secs.toFixed(2)} s per frame at ${fps}fps`;
    }

    repeatInput.addEventListener("input", update);
    if (fpsInput) fpsInput.addEventListener("input", update);
    update();
  }

  function closeVideoModal() {
    const modal = document.querySelector("[data-video-modal]");
    if (!modal || modal.hidden) return;
    modal.hidden = true;
    modal.querySelectorAll("video").forEach((video) => video.pause());
  }

  function formatElapsed(seconds) {
    if (seconds === null || seconds === undefined) return "--:--:--";
    const total = Math.max(0, Math.floor(seconds));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const secs = total % 60;
    return [hours, minutes, secs].map((part) => String(part).padStart(2, "0")).join(":");
  }

  function formatDateTime(value) {
    if (!value) return "Pending";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value.replace("T", " ").slice(0, 19);
    const pad = (part) => String(part).padStart(2, "0");
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
  }

  function setupDailyWindowControls() {
    document.querySelectorAll("[data-toggle-daily-window]").forEach((toggle) => {
      if (toggle.dataset.dailyWindowBound === "1") {
        syncDailyWindow(toggle);
        return;
      }
      toggle.dataset.dailyWindowBound = "1";
      toggle.addEventListener("change", () => syncDailyWindow(toggle));
      syncDailyWindow(toggle);
    });
  }

  function syncDailyWindow(toggle) {
    const scope = toggle.closest("fieldset") || toggle.closest("form") || document;
    const fields = scope.querySelector("[data-daily-window-fields]");
    if (!fields) return;
    fields.querySelectorAll("input").forEach((input) => {
      input.disabled = !toggle.checked;
    });
    fields.classList.toggle("disabled", !toggle.checked);
    fields.setAttribute("aria-disabled", toggle.checked ? "false" : "true");
  }

  function setupEarliestAvailableControls() {
    document.querySelectorAll("[data-toggle-earliest-available]").forEach((toggle) => {
      if (toggle.dataset.earliestAvailableBound === "1") {
        syncEarliestAvailable(toggle);
        return;
      }
      toggle.dataset.earliestAvailableBound = "1";
      toggle.addEventListener("change", () => syncEarliestAvailable(toggle));
      syncEarliestAvailable(toggle);
    });
  }

  function syncEarliestAvailable(toggle) {
    const scope = toggle.closest("fieldset") || toggle.closest("form") || document;
    const startField = scope.querySelector("[data-start-date-field]");
    const startInput = scope.querySelector('input[name="start_at"]');
    if (!startInput) return;
    startInput.disabled = toggle.checked;
    startField?.classList.toggle("disabled-field", toggle.checked);
    startField?.setAttribute("aria-disabled", toggle.checked ? "true" : "false");
  }

  function setupOutputScaleControls() {
    document.querySelectorAll("[data-output-scale-mode]").forEach((select) => {
      if (select.dataset.outputScaleBound === "1") {
        syncOutputScale(select);
        return;
      }
      select.dataset.outputScaleBound = "1";
      select.addEventListener("change", () => syncOutputScale(select));
      syncOutputScale(select);
    });
  }

  function syncOutputScale(select) {
    const scope = select.closest("fieldset") || select.closest("form") || document;
    const customField = scope.querySelector("[data-output-scale-custom]");
    const customInput = customField?.querySelector('input[name="output_scale_width"]');
    if (!customInput) return;
    const enabled = select.value === "custom";
    customInput.disabled = !enabled;
    customField?.classList.toggle("disabled-field", !enabled);
    customField?.setAttribute("aria-disabled", enabled ? "false" : "true");
  }

  function setupSetupControls() {
    document.querySelectorAll("[data-detect-host]").forEach((button) => {
      if (button.dataset.detectHostBound === "1") return;
      button.dataset.detectHostBound = "1";
      button.addEventListener("click", detectHost);
    });

    document.querySelectorAll("[data-toggle-secret]").forEach((button) => {
      if (button.dataset.secretToggleBound === "1") {
        syncSecretToggle(button);
        return;
      }
      button.dataset.secretToggleBound = "1";
      button.addEventListener("click", () => {
        const input = button.closest(".secret-field")?.querySelector("[data-secret-input]");
        if (!input) return;
        input.type = input.type === "password" ? "text" : "password";
        syncSecretToggle(button);
      });
      syncSecretToggle(button);
    });

    document.querySelectorAll("[data-choose-output-dir]").forEach((button) => {
      if (button.dataset.outputDirBound === "1") return;
      button.dataset.outputDirBound = "1";
      button.addEventListener("click", chooseOutputDirectory);
    });

    document.querySelectorAll("[data-discover-site-manager]").forEach((button) => {
      if (button.dataset.siteManagerBound === "1") return;
      button.dataset.siteManagerBound = "1";
      button.addEventListener("click", discoverSiteManagerHosts);
    });

    document.querySelectorAll("[data-test-console]").forEach((button) => {
      if (button.dataset.testConsoleBound === "1") return;
      button.dataset.testConsoleBound = "1";
      button.addEventListener("click", testConsoleConnection);
    });

    // Console card collapse toggles (click on header)
    document.querySelectorAll("[data-console-header]").forEach((header) => {
      if (header.dataset.consoleHeaderBound === "1") return;
      header.dataset.consoleHeaderBound = "1";
      header.addEventListener("click", () => toggleConsoleCard(header.dataset.consoleHeader));
    });
    document.querySelectorAll("[data-collapse-console]").forEach((btn) => {
      if (btn.dataset.collapseConsoleBound === "1") return;
      btn.dataset.collapseConsoleBound = "1";
      btn.addEventListener("click", () => toggleConsoleCard(btn.dataset.collapseConsole));
    });
    initConsoleCardStates();

    // Enabled/disabled instant toggle
    document.querySelectorAll("[data-toggle-enabled]").forEach((checkbox) => {
      if (checkbox.dataset.toggleEnabledBound === "1") return;
      checkbox.dataset.toggleEnabledBound = "1";
      checkbox.addEventListener("change", async () => {
        const consoleId = checkbox.dataset.toggleEnabled;
        try {
          await fetch(`/setup/consoles/${consoleId}/enabled`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ enabled: checkbox.checked }),
          });
        } catch (_) {
          checkbox.checked = !checkbox.checked; // revert on network error
        }
      });
    });

    // Copy test result buttons on existing console cards
    document.querySelectorAll("[data-copy-test]").forEach((btn) => {
      if (btn.dataset.copyTestBound === "1") return;
      btn.dataset.copyTestBound = "1";
      btn.addEventListener("click", () => {
        const consoleId = btn.dataset.copyTest;
        const resultEl = document.querySelector(`[data-test-result-${consoleId}]`);
        if (resultEl) navigator.clipboard.writeText(resultEl.textContent).catch(() => {});
      });
    });

    setupConsoleDragReorder();
    setupAddConsoleModal();
  }

  function toggleConsoleCard(consoleId) {
    const body = document.getElementById(`console-body-${consoleId}`);
    const btn = document.querySelector(`[data-collapse-console="${consoleId}"]`);
    if (!body || !btn) return;
    const willExpand = body.hidden;
    body.hidden = !willExpand;
    btn.setAttribute("aria-expanded", willExpand ? "true" : "false");
    const key = `blink.console.expanded.${consoleId}`;
    if (willExpand) {
      localStorage.setItem(key, "1");
    } else {
      localStorage.removeItem(key);
    }
  }

  function initConsoleCardStates() {
    document.querySelectorAll(".console-card[data-console-id]").forEach((card) => {
      const consoleId = card.dataset.consoleId;
      const body = document.getElementById(`console-body-${consoleId}`);
      const btn = document.querySelector(`[data-collapse-console="${consoleId}"]`);
      if (!body || !btn) return;
      const isExpanded = localStorage.getItem(`blink.console.expanded.${consoleId}`) === "1";
      body.hidden = !isExpanded;
      btn.setAttribute("aria-expanded", isExpanded ? "true" : "false");
    });
  }

  function setupConsoleDragReorder() {
    const list = document.querySelector("[data-console-list]");
    if (!list || list.dataset.dragBound === "1") return;
    list.dataset.dragBound = "1";

    let dragging = null;   // original card (dimmed in place)
    let ghost = null;      // floating clone that follows the cursor
    let line = null;       // blue insertion line
    let offsetY = 0;       // pointer offset within the card

    function getLine() {
      if (!line) {
        line = document.createElement("div");
        line.className = "drag-placeholder";
      }
      return line;
    }

    function cleanup() {
      if (ghost) { ghost.remove(); ghost = null; }
      getLine().remove();
      if (dragging) dragging.classList.remove("dragging");
      dragging = null;
    }

    list.addEventListener("pointerdown", (e) => {
      const handle = e.target.closest("[data-drag-handle]");
      if (!handle) return;
      const card = handle.closest(".console-card[data-console-id]");
      if (!card) return;
      e.preventDefault();

      const rect = card.getBoundingClientRect();
      offsetY = e.clientY - rect.top;

      dragging = card;
      card.classList.add("dragging");

      // Floating ghost that tracks the cursor
      ghost = card.cloneNode(true);
      ghost.classList.add("drag-ghost");
      ghost.style.width = `${rect.width}px`;
      ghost.style.top = `${rect.top}px`;
      ghost.style.left = `${rect.left}px`;
      document.body.appendChild(ghost);

      list.setPointerCapture(e.pointerId);
    });

    list.addEventListener("pointermove", (e) => {
      if (!dragging || !ghost) return;
      e.preventDefault();

      // Ghost follows cursor
      ghost.style.top = `${e.clientY - offsetY}px`;

      // Blue insertion line tracks target position
      const ln = getLine();
      const cards = Array.from(
        list.querySelectorAll(".console-card[data-console-id]:not(.dragging)")
      );
      let insertBefore = null;
      for (const card of cards) {
        const r = card.getBoundingClientRect();
        if (e.clientY < r.top + r.height / 2) { insertBefore = card; break; }
      }
      insertBefore ? list.insertBefore(ln, insertBefore) : list.appendChild(ln);
    });

    list.addEventListener("pointerup", async () => {
      if (!dragging) return;
      const ln = getLine();
      // Only reorder if the insertion line was actually placed
      if (ln.parentNode === list) list.insertBefore(dragging, ln);
      cleanup();

      const ids = Array.from(list.querySelectorAll(".console-card[data-console-id]"))
        .map((c) => parseInt(c.dataset.consoleId, 10));
      try {
        await fetch("/setup/consoles/reorder", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ids }),
        });
      } catch (_) {}
    });

    list.addEventListener("pointercancel", cleanup);
  }

  function setupAddConsoleModal() {
    const modal = document.getElementById("add-console-modal");
    if (!modal || modal.dataset.modalBound === "1") return;
    modal.dataset.modalBound = "1";

    // Open
    document.querySelectorAll("[data-open-add-console]").forEach((btn) => {
      btn.addEventListener("click", () => openAddConsoleModal());
    });
    // Close
    modal.querySelectorAll("[data-close-add-console]").forEach((btn) => {
      btn.addEventListener("click", () => closeAddConsoleModal());
    });
    modal.addEventListener("click", (e) => {
      if (e.target === modal) closeAddConsoleModal();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !modal.hidden) closeAddConsoleModal();
    });

    // Tab switching
    modal.querySelectorAll("[data-add-console-tab]").forEach((btn) => {
      btn.addEventListener("click", () => switchAddConsoleTab(btn.dataset.addConsoleTab));
    });

    // Test connection for new console
    const testBtn = modal.querySelector("[data-test-add-console]");
    if (testBtn) {
      testBtn.addEventListener("click", async () => {
        const form = document.getElementById("add-console-form");
        const testArea = document.getElementById("add-console-test-area");
        const outputEl = document.getElementById("add-console-test-output");
        testBtn.disabled = true;
        if (testArea) testArea.hidden = false;
        if (outputEl) { outputEl.textContent = "Testing…"; outputEl.style.color = ""; }
        try {
          const formData = new FormData(form);
          const response = await fetch("/setup/consoles/test-credentials", { method: "POST", body: formData });
          const data = await response.json();
          if (outputEl) {
            outputEl.textContent = data.ok ? (data.message || "Connected.") : ("Error: " + (data.error || "Unknown error"));
            outputEl.style.color = data.ok ? "var(--ok)" : "";
          }
        } catch (err) {
          if (outputEl) outputEl.textContent = "Request failed: " + err.message;
        } finally {
          testBtn.disabled = false;
        }
      });
    }

    // Copy test result in modal
    const copyBtn = modal.querySelector("[data-copy-add-console-test]");
    if (copyBtn) {
      copyBtn.addEventListener("click", () => {
        const outputEl = document.getElementById("add-console-test-output");
        if (outputEl) navigator.clipboard.writeText(outputEl.textContent).catch(() => {});
      });
    }
  }

  function openAddConsoleModal() {
    const modal = document.getElementById("add-console-modal");
    if (!modal) return;
    modal.hidden = false;
    // All controls were bound at page load — just focus the first visible input
    const firstInput = modal.querySelector("[data-add-console-section='direct'] input:not([type=hidden])");
    if (firstInput && !firstInput.disabled) firstInput.focus();
  }

  function closeAddConsoleModal() {
    const modal = document.getElementById("add-console-modal");
    if (!modal) return;
    modal.hidden = true;
    // Reset form
    const form = document.getElementById("add-console-form");
    if (form) form.reset();
    const testArea = document.getElementById("add-console-test-area");
    if (testArea) testArea.hidden = true;
    // Reset to Direct tab
    switchAddConsoleTab("direct");
  }

  function switchAddConsoleTab(tab) {
    const modal = document.getElementById("add-console-modal");
    if (!modal) return;
    modal.querySelectorAll("[data-add-console-tab]").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.addConsoleTab === tab);
    });
    modal.querySelectorAll("[data-add-console-section]").forEach((section) => {
      const isActive = section.dataset.addConsoleSection === tab;
      section.hidden = !isActive;
      // Disable inputs in inactive sections so they don't interfere with form submission
      section.querySelectorAll("input:not([type=hidden]), select, textarea").forEach((input) => {
        input.disabled = !isActive;
      });
    });
    const typeField = document.getElementById("add-console-type-field");
    if (typeField) typeField.value = tab === "cloud" ? "SITE_MANAGER" : "DIRECT";
    // Clear test result when switching tabs
    const testArea = document.getElementById("add-console-test-area");
    if (testArea) testArea.hidden = true;
  }

  async function discoverSiteManagerHosts(event) {
    const button = event.currentTarget;
    const form = button.closest("form") || button.closest(".panel") || document;
    const apiKeyInput = form.querySelector("[data-site-manager-api-key]");
    const resultContainer = form.querySelector("[data-site-manager-results]");
    if (!apiKeyInput || !resultContainer) return;

    const apiKey = apiKeyInput.value.trim();
    if (!apiKey) {
      resultContainer.innerHTML = '<p class="notice error">Enter a UI API key first.</p>';
      return;
    }

    button.disabled = true;
    resultContainer.innerHTML = '<p class="field-help">Discovering consoles...</p>';

    try {
      const response = await fetch(`/setup/site-manager/hosts?api_key=${encodeURIComponent(apiKey)}`, {
        headers: { Accept: "application/json" },
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Discovery failed.");

      const hosts = data.hosts || [];
      if (hosts.length === 0) {
        resultContainer.innerHTML = '<p class="field-help">No Protect-enabled consoles found for this API key.</p>';
        return;
      }

      const items = hosts
        .map(
          (h) => `
        <label class="check">
          <input type="radio" name="_sm_host_pick" value="${h.hostId}"
            data-sm-host-id="${h.hostId}" data-sm-host-name="${h.displayName}">
          ${h.displayName}${h.hostname ? ` <span class="muted">(${h.hostname})</span>` : ""}
        </label>`
        )
        .join("");
      resultContainer.innerHTML = `<div style="display:grid;gap:8px;margin-top:4px">${items}</div>`;

      resultContainer.querySelectorAll("input[type=radio][name=_sm_host_pick]").forEach((radio) => {
        radio.addEventListener("change", () => {
          const hiddenId = form.querySelector("[data-sm-host-id-field]");
          const nameInput = form.querySelector("[data-sm-name-field]");
          if (hiddenId) hiddenId.value = radio.dataset.smHostId;
          if (nameInput && !nameInput.value) nameInput.value = radio.dataset.smHostName;
        });
      });
    } catch (error) {
      resultContainer.innerHTML = `<div class="notice error">${error.message || "Could not reach the Site Manager API."}</div>`;
    } finally {
      button.disabled = false;
    }
  }

  async function testConsoleConnection(event) {
    const button = event.currentTarget;
    const testUrl = button.dataset.testConsole;
    if (!testUrl) return;

    // Extract console id from URL: /setup/consoles/{id}/test
    const consoleId = testUrl.split("/").slice(-2, -1)[0];
    const resultEl = document.querySelector(`[data-test-result-${consoleId}]`);
    const wrapperEl = document.getElementById(`test-wrapper-${consoleId}`);

    button.disabled = true;
    if (wrapperEl) wrapperEl.hidden = false;
    if (resultEl) resultEl.textContent = "Testing…";

    try {
      const response = await fetch(testUrl, { headers: { Accept: "application/json" } });
      const data = await response.json();
      if (resultEl) resultEl.textContent = JSON.stringify(data, null, 2);
    } catch (err) {
      if (resultEl) resultEl.textContent = "Request failed: " + err.message;
    } finally {
      button.disabled = false;
    }
  }

  async function detectHost(event) {
    const button = event.currentTarget;
    const form = button.closest("form") || document;
    const input = form.querySelector("[data-unifi-host]");
    const status = form.querySelector("[data-detect-host-status]");
    if (!input) return;
    button.disabled = true;
    if (status) status.textContent = "Detecting default gateway...";
    try {
      const response = await fetch("/setup/detect-host", { headers: { Accept: "application/json" } });
      const data = await response.json();
      if (!response.ok || !data.host) throw new Error(data.error || "Could not detect a default gateway.");
      input.value = data.host;
      if (status) status.textContent = `Detected ${data.gateway}. Save settings to keep this host.`;
    } catch (error) {
      if (status) status.textContent = error.message || "Could not detect a default gateway.";
    } finally {
      button.disabled = false;
    }
  }

  function syncSecretToggle(button) {
    const input = button.closest(".secret-field")?.querySelector("[data-secret-input]");
    if (!input) return;
    const hidden = input.type === "password";
    button.title = hidden ? "Show API key" : "Hide API key";
    button.setAttribute("aria-label", button.title);
  }

  async function chooseOutputDirectory(event) {
    const button = event.currentTarget;
    const form = button.closest("form") || document;
    const input = form.querySelector("[data-output-dir]");
    const status = form.querySelector("[data-output-dir-status]");
    if (!input) return;
    const api = window.pywebview && window.pywebview.api;
    if (!api || typeof api.select_output_directory !== "function") {
      if (status) status.textContent = "Native folder selection is available in Blink.app. Type or paste a path here in the browser.";
      return;
    }
    button.disabled = true;
    if (status) status.textContent = "Opening folder picker...";
    try {
      const selected = await api.select_output_directory(input.value || "");
      if (selected) {
        input.value = selected;
        if (status) status.textContent = "Folder selected. Save settings to keep this path.";
      } else if (status) {
        status.textContent = "Folder selection canceled.";
      }
    } catch (error) {
      if (status) status.textContent = error.message || "Could not open the folder picker.";
    } finally {
      button.disabled = false;
    }
  }

  function stopJobStatusPolling() {
    if (jobStatusTimer !== null) {
      window.clearInterval(jobStatusTimer);
      jobStatusTimer = null;
    }
  }

  function rebuildFrameTable(container, frames) {
    if (!frames || frames.length === 0) {
      container.innerHTML = '<p class="empty">No frames recorded yet.</p>';
      return;
    }
    const rows = frames
      .map(
        (f) =>
          `<tr>
            <td>${f.requested_at || ""}</td>
            <td><code>${f.camera_id || ""}</code></td>
            <td><span class="status ${f.status === "success" ? "ok" : "bad"}">${f.status || ""}</span></td>
            <td>${f.source_method || ""}</td>
            <td>${f.error || ""}</td>
          </tr>`
      )
      .join("");
    container.innerHTML = `<table>
      <thead><tr><th>Requested</th><th>Camera</th><th>Status</th><th>Source</th><th>Error</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
  }

  function startJobStatusPolling() {
    stopJobStatusPolling();
    const panel = document.querySelector("[data-job-status-url]");
    if (!panel) return;
    const url = panel.dataset.jobStatusUrl;
    const statusEl = panel.querySelector("[data-job-status]");
    const progressLabel = panel.querySelector("[data-job-progress-label]");
    const progressBar = panel.querySelector("[data-job-progress-bar]");
    const message = panel.querySelector("[data-job-message]");
    const elapsed = panel.querySelector("[data-job-elapsed]");
    const rangeStart = panel.querySelector("[data-job-range-start]");
    const rangeEnd = panel.querySelector("[data-job-range-end]");
    const dailyWindow = panel.querySelector("[data-job-daily-window]");
    const counts = panel.querySelector("[data-job-counts]");
    const framesSection = document.querySelector("[data-frames-url]");
    const framesBody = framesSection ? framesSection.querySelector("[data-frames-body]") : null;
    const framesUrl = framesSection ? framesSection.dataset.framesUrl : null;
    let tickCount = 0;

    async function refresh() {
      const response = await fetch(url, { headers: { Accept: "application/json" } });
      if (!response.ok) return false;
      const data = await response.json();
      const progress = Math.max(0, Math.min(Number(data.progress || 0), 100));
      if (statusEl) statusEl.textContent = data.status;
      if (progressLabel) progressLabel.textContent = `${progress.toFixed(1)}%`;
      if (progressBar) progressBar.style.width = `${progress}%`;
      if (message) message.textContent = data.message || "";
      if (elapsed) elapsed.textContent = formatElapsed(data.elapsed_seconds);
      if (rangeStart) rangeStart.textContent = formatDateTime(data.resolved_start_at);
      if (rangeEnd) rangeEnd.textContent = formatDateTime(data.resolved_end_at);
      if (dailyWindow) dailyWindow.textContent = data.daily_window_enabled ? `${data.daily_start}-${data.daily_end}` : "Full day";
      if (counts) counts.textContent = `${data.processed_frame_count} of ${data.planned_frame_count} requested frame timestamps processed`;
      return data.status === "queued" || data.status === "running";
    }

    async function refreshFrames() {
      if (!framesUrl || !framesBody) return;
      try {
        const response = await fetch(framesUrl, { headers: { Accept: "application/json" } });
        if (!response.ok) return;
        const data = await response.json();
        rebuildFrameTable(framesBody, data.frames);
      } catch (_) {}
    }

    if (panel.dataset.jobActive !== "1") {
      refresh();
      return;
    }

    refresh();
    jobStatusTimer = window.setInterval(async () => {
      try {
        tickCount++;
        const keepGoing = await refresh();
        if (tickCount % 5 === 0) await refreshFrames();
        if (!keepGoing) {
          stopJobStatusPolling();
          window.location.reload();
        }
      } catch (_error) {
        stopJobStatusPolling();
      }
    }, 1000);
  }

  document.addEventListener("DOMContentLoaded", initializePage);
  window.addEventListener("pageshow", initializePage);
  window.addEventListener("pagehide", stopJobStatusPolling);
})();
