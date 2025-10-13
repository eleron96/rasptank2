(function () {
  const API_URL = "/api/servo/shoulder";
  const HOST_CARD_TITLE = "Arm Control";
  const PANEL_ID = "shoulder-calibration";

  function onReady(fn) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn, { once: true });
    } else {
      fn();
    }
  }

  function ensureStyle() {
    if (document.getElementById(`${PANEL_ID}-style`)) {
      return;
    }
    const style = document.createElement("style");
    style.id = `${PANEL_ID}-style`;
    style.textContent = `
      .${PANEL_ID} {
        margin-top: 12px;
        padding: 12px;
        background: rgba(255,255,255,0.06);
        border-radius: 10px;
        display: grid;
        gap: 10px;
      }
      .${PANEL_ID} h4 {
        margin: 0;
        font-size: 16px;
        font-weight: 600;
        color: rgba(255,255,255,0.9);
      }
      .${PANEL_ID} label {
        display: flex;
        justify-content: space-between;
        align-items: center;
        font-size: 14px;
        gap: 10px;
        color: rgba(255,255,255,0.85);
      }
      .${PANEL_ID} input[type="number"] {
        flex: 0 0 110px;
        border-radius: 6px;
        border: 1px solid rgba(255,255,255,0.18);
        background: rgba(0,0,0,0.25);
        padding: 6px 8px;
        color: #fff;
        font-size: 14px;
      }
      .${PANEL_ID} input[type="number"]:focus {
        border-color: #42a5f5;
        outline: none;
      }
      .${PANEL_ID} .actions {
        display: flex;
        justify-content: flex-end;
        gap: 8px;
      }
      .${PANEL_ID} button {
        cursor: pointer;
        border: none;
        border-radius: 6px;
        padding: 8px 14px;
        font-size: 14px;
        font-weight: 600;
        background: linear-gradient(135deg,#42a5f5,#478ed1);
        color: #fff;
        transition: filter 0.2s ease;
      }
      .${PANEL_ID} button:disabled {
        opacity: 0.6;
        cursor: default;
      }
      .${PANEL_ID} button:not(:disabled):hover {
        filter: brightness(1.1);
      }
      .${PANEL_ID} .hint {
        font-size: 12px;
        color: rgba(255,255,255,0.65);
      }
      .${PANEL_ID} .status {
        font-size: 12px;
        min-height: 16px;
        color: rgba(255,255,255,0.8);
      }
      .${PANEL_ID} .status.error {
        color: #ff9e9e;
      }
    `;
    document.head.appendChild(style);
  }

  function findArmControlWrapper() {
    const cards = document.querySelectorAll(".mod-sheet");
    for (const card of cards) {
      const title = card.querySelector(".mod-title");
      if (title && title.textContent.trim() === HOST_CARD_TITLE) {
        return card.querySelector(".mod-wrapper");
      }
    }
    return null;
  }

  function fetchCalibration() {
    return fetch(API_URL, { credentials: "same-origin" }).then((res) => {
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    });
  }

  function postCalibration(payload) {
    return fetch(API_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify(payload),
    }).then((res) =>
      res.json().then((body) => {
        if (!res.ok || body.error) {
          const message = body.error || `HTTP ${res.status}`;
          throw new Error(message);
        }
        return body;
      })
    );
  }

  function buildPanel(wrapper) {
    if (!wrapper || wrapper.querySelector(`.${PANEL_ID}`)) {
      return;
    }
    ensureStyle();

    const panel = document.createElement("div");
    panel.className = PANEL_ID;
    panel.innerHTML = `
      <h4>Shoulder Calibration</h4>
      <label>
        Initial angle (°)
        <input type="number" min="0" max="180" step="1" value="90" id="${PANEL_ID}-base" />
      </label>
      <label>
        Raise offset (° from base)
        <input type="number" min="0" max="180" step="1" value="90" id="${PANEL_ID}-raise" />
      </label>
      <div class="hint">Initial angle is absolute; raise is the additional travel from that base.</div>
      <div class="actions">
        <button type="button" id="${PANEL_ID}-save">Save</button>
      </div>
      <div class="status" id="${PANEL_ID}-status"></div>
    `;
    wrapper.appendChild(panel);

    const baseInput = panel.querySelector(`#${PANEL_ID}-base`);
    const raiseInput = panel.querySelector(`#${PANEL_ID}-raise`);
    const saveBtn = panel.querySelector(`#${PANEL_ID}-save`);
    const status = panel.querySelector(`#${PANEL_ID}-status`);

    function setStatus(message, isError) {
      status.textContent = message || "";
      status.classList.toggle("error", Boolean(isError));
    }

    function fillValues(data) {
      const calibration = data && data.calibration ? data.calibration : data;
      if (!calibration) {
        return;
      }
      if (typeof calibration.base_angle === "number") {
        baseInput.value = calibration.base_angle.toFixed(0);
      }
      if (typeof calibration.raise_angle === "number") {
        raiseInput.value = calibration.raise_angle.toFixed(0);
      }
    }

    saveBtn.addEventListener("click", () => {
      const base = Number(baseInput.value);
      const raise = Number(raiseInput.value);
      if (Number.isNaN(base) || Number.isNaN(raise)) {
        setStatus("Enter valid angle values.", true);
        return;
      }
      setStatus("Saving...", false);
      saveBtn.disabled = true;
      postCalibration({ base_angle: base, raise_angle: raise })
        .then((data) => {
          fillValues(data);
          setStatus("Calibration saved.", false);
        })
        .catch((err) => {
          setStatus(err.message || "Failed to save.", true);
        })
        .finally(() => {
          saveBtn.disabled = false;
        });
    });

    fetchCalibration()
      .then((data) => {
        fillValues(data);
        setStatus("", false);
      })
      .catch((err) => {
        setStatus(`Failed to load calibration: ${err.message}`, true);
      });
  }

  function init() {
    const wrapper = findArmControlWrapper();
    if (wrapper) {
      buildPanel(wrapper);
      return;
    }
    const observer = new MutationObserver(() => {
      const targetWrapper = findArmControlWrapper();
      if (targetWrapper) {
        observer.disconnect();
        buildPanel(targetWrapper);
      }
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }

  onReady(init);
})();
