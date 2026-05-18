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

  function setView(root, view, storageKey) {
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
  }

  function setupRoot(root) {
    const toggle = root.closest("main").querySelector("[data-camera-view-toggle]");
    const storageKey = toggle ? toggle.dataset.storageKey : "blink.cameraView";
    const saved = localStorage.getItem(storageKey) || "list";
    setView(root, saved === "grid" ? "grid" : "list", storageKey);

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
    setupSetupControls();
    startJobStatusPolling();
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
