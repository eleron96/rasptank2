(function () {
  const API_URL = "/api/calibration";
  const FALLBACK_REFRESH_MS = 15000;
  const SSE_URL = "/api/events";
  let eventSource = null;

  function createPanel() {
    if (document.getElementById("calibration-panel")) {
      return;
    }

    const style = document.createElement("style");
    style.textContent = `
      #calibration-panel {
        position: fixed;
        right: 16px;
        bottom: 16px;
        width: 260px;
        background: rgba(33, 33, 33, 0.9);
        color: #fafafa;
        border-radius: 12px;
        box-shadow: 0 10px 30px rgba(0,0,0,0.35);
        font-family: "Roboto", sans-serif;
        z-index: 9999;
        backdrop-filter: blur(4px);
      }
      #calibration-panel.collapsed .calib-body {
        display: none;
      }
      #calibration-panel .calib-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 10px 14px;
        border-bottom: 1px solid rgba(255,255,255,0.08);
        font-weight: 600;
        font-size: 15px;
        letter-spacing: 0.02em;
        text-transform: uppercase;
      }
      #calibration-panel button {
        cursor: pointer;
        border: none;
        border-radius: 6px;
        padding: 8px 12px;
        font-weight: 500;
        font-size: 14px;
        transition: 0.2s ease;
      }
      #calibration-panel .calib-toggle {
        background: transparent;
        color: inherit;
        font-size: 18px;
        width: 28px;
        height: 28px;
        line-height: 0;
      }
      #calibration-panel .calib-toggle:hover {
        background: rgba(255,255,255,0.08);
      }
      #calibration-panel .calib-body {
        padding: 14px;
        display: grid;
        gap: 10px;
      }
      #calibration-panel .calib-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        font-size: 14px;
      }
      #calibration-panel .calib-row span.value {
        font-weight: 600;
      }
      #calibration-panel label {
        display: flex;
        flex-direction: column;
        font-size: 13px;
        gap: 6px;
      }
      #calibration-panel input[type="number"] {
        border-radius: 6px;
        border: 1px solid rgba(255,255,255,0.12);
        padding: 8px;
        background: rgba(0,0,0,0.25);
        color: #fff;
        font-size: 14px;
        outline: none;
      }
      #calibration-panel input[type="number"]:focus {
        border-color: #42a5f5;
      }
      #calibration-panel .calib-action {
        background: linear-gradient(135deg,#42a5f5,#478ed1);
        color: #fff;
      }
      #calibration-panel .calib-action:hover {
        filter: brightness(1.1);
      }
      #calibration-panel .calib-message {
        min-height: 18px;
        font-size: 12px;
        color: rgba(255,255,255,0.8);
      }
      #calibration-panel .calib-message.error {
        color: #ff9494;
      }
    `;
    document.head.appendChild(style);

    const panel = document.createElement("div");
    panel.id = "calibration-panel";
    panel.innerHTML = `
      <div class="calib-header">
        <span>Settings</span>
        <button type="button" class="calib-toggle" aria-label="Toggle settings">-</button>
      </div>
      <div class="calib-body">
        <div class="calib-row">
          <span>Calibrated</span>
          <span class="value" id="calib-current">-- V</span>
        </div>
        <div class="calib-row">
          <span>Raw</span>
          <span class="value" id="calib-raw">-- V</span>
        </div>
        <label>
          Current voltage (V)
          <input type="number" step="0.01" min="0" value="8.40" id="calib-input" />
        </label>
        <button type="button" class="calib-action" id="calib-save">Save</button>
        <div class="calib-message" id="calib-message"></div>
      </div>
    `;
    document.body.appendChild(panel);

    const toggle = panel.querySelector(".calib-toggle");
    const saveBtn = panel.querySelector("#calib-save");
    const input = panel.querySelector("#calib-input");
    const currentEl = panel.querySelector("#calib-current");
    const rawEl = panel.querySelector("#calib-raw");
    const messageEl = panel.querySelector("#calib-message");

    function setMessage(text, isError) {
      messageEl.textContent = text || "";
      messageEl.classList.toggle("error", Boolean(isError));
    }

    function updateReadings(data) {
      if (!data) {
        return;
      }
      if (typeof data.voltage === "number" && !Number.isNaN(data.voltage)) {
        currentEl.textContent = `${data.voltage.toFixed(2)} V`;
      }
      const rawValue = typeof data.raw_voltage === "number" && !Number.isNaN(data.raw_voltage)
        ? data.raw_voltage
        : (typeof data.raw_sample === "number" && !Number.isNaN(data.raw_sample) ? data.raw_sample : null);
      if (rawValue !== null) {
        rawEl.textContent = `${rawValue.toFixed(2)} V`;
      }
      if (typeof data.actual_voltage === "number" && !Number.isNaN(data.actual_voltage)) {
        input.value = data.actual_voltage.toFixed(2);
      } else if (data.calibration && typeof data.calibration.scale === "number" && !input.value) {
        input.value = data.calibration.scale.toFixed(2);
      }
    }

    async function refresh() {
      try {
        const res = await fetch(API_URL, { credentials: "same-origin" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        updateReadings(data);
        setMessage("", false);
      } catch (err) {
        setMessage(`Failed to fetch calibration: ${err.message}`, true);
      }
    }

    async function submit() {
      const voltage = parseFloat(input.value);
      if (!voltage || voltage <= 0) {
        setMessage("Enter a positive voltage value.", true);
        return;
      }
      setMessage("Saving...", false);
      saveBtn.disabled = true;
      try {
        const res = await fetch(API_URL, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ voltage }),
        });
        const data = await res.json();
        if (!res.ok || data.error) {
          throw new Error(data.error || `HTTP ${res.status}`);
        }
        updateReadings(data);
        input.value = voltage.toFixed(2);
        setMessage("Calibration saved.", false);
      } catch (err) {
        setMessage(`Save failed: ${err.message}`, true);
      } finally {
        saveBtn.disabled = false;
      }
    }

    toggle.addEventListener("click", () => {
      const collapsed = panel.classList.toggle("collapsed");
      toggle.textContent = collapsed ? "+" : "-";
    });

    saveBtn.addEventListener("click", submit);

    refresh();

    function connectStream() {
      if (!window.EventSource) {
        setInterval(refresh, FALLBACK_REFRESH_MS);
        return;
      }
      try {
        if (eventSource) {
          eventSource.close();
        }
        eventSource = new EventSource(SSE_URL);
        window.__calibrationEventSource = eventSource;
        eventSource.addEventListener("battery_status", (evt) => {
          try {
            const payload = JSON.parse(evt.data);
            updateReadings(payload);
            setMessage("", false);
          } catch (error) {
            console.error("battery_status parse error", error);
          }
        });
        eventSource.addEventListener("battery_calibration", (evt) => {
          try {
            const payload = JSON.parse(evt.data);
            if (payload && typeof payload.scale === "number" && !Number.isNaN(payload.scale)) {
              setMessage("Calibration file updated.", false);
            }
          } catch (error) {
            console.error("battery_calibration parse error", error);
          }
        });
        eventSource.addEventListener("error", () => {
          setMessage("Event stream disconnected. Retrying...", true);
          if (eventSource) {
            eventSource.close();
            eventSource = null;
          }
          setTimeout(connectStream, 3000);
        });
      } catch (err) {
        console.error("Failed to open EventSource", err);
        setInterval(refresh, FALLBACK_REFRESH_MS);
      }
    }

    connectStream();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", createPanel);
  } else {
    createPanel();
  }
})();
