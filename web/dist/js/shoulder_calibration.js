(function () {
  const API_URL = "/api/servo/shoulder";
  const CARD_ID = "settings-card";
  const MODAL_ID = "settings-modal";

  function onReady(fn) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn, { once: true });
    } else {
      fn();
    }
  }

  function fetchCalibration() {
    return fetch(API_URL, { credentials: "same-origin" }).then((res) => {
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
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

  function findSettingsColumn() {
    const titles = document.querySelectorAll(".mod-sheet .mod-title");
    for (const title of titles) {
      if (!title || !title.textContent) {
        continue;
      }
      const label = title.textContent.trim().toLowerCase();
      if (label === "hard ware" || label === "hardware" || label === "оборудование") {
        const column = title.closest(".v-col");
        if (column) {
          return column;
        }
      }
    }
    const columns = document.querySelectorAll(".controll-area .v-row > .v-col");
    if (columns.length) {
      return columns[columns.length - 1];
    }
    return document.querySelector(".area-wrapper .v-container") || document.body;
  }

  let modalInstance = null;

  function getModalInstance() {
    if (modalInstance) {
      return modalInstance;
    }

    const root = document.createElement("div");
    root.id = MODAL_ID;
    root.className = "settings-modal";
    root.innerHTML = `
      <div class="settings-modal__backdrop" data-action="close"></div>
      <div class="settings-modal__dialog" role="dialog" aria-modal="true" aria-labelledby="${MODAL_ID}-title">
        <div class="settings-modal__header">
          <h3 class="settings-modal__title" id="${MODAL_ID}-title">Калибровка плеча</h3>
          <button type="button" class="settings-modal__close" data-action="close" aria-label="Закрыть">×</button>
        </div>
        <div class="settings-modal__content">
          <div class="settings-modal__field">
            <label for="${MODAL_ID}-base">Базовый угол (°)</label>
            <input type="number" min="0" max="180" step="1" id="${MODAL_ID}-base" autocomplete="off" inputmode="decimal" />
          </div>
          <div class="settings-modal__field">
            <label for="${MODAL_ID}-raise">Угол подъёма (°)</label>
            <input type="number" min="5" max="180" step="1" id="${MODAL_ID}-raise" autocomplete="off" inputmode="decimal" />
          </div>
          <div class="settings-modal__hint">
            Базовый угол — абсолютное положение сервопривода. Значение «подъём» задаёт дополнительный ход вверх от базового положения.
          </div>
          <div class="settings-modal__status" id="${MODAL_ID}-status"></div>
        </div>
        <div class="settings-modal__actions">
          <button type="button" class="settings-modal__secondary" data-action="cancel">Отмена</button>
          <button type="button" class="settings-modal__primary" data-action="save">Сохранить</button>
        </div>
      </div>
    `;
    document.body.appendChild(root);

    const baseInput = root.querySelector(`#${MODAL_ID}-base`);
    const raiseInput = root.querySelector(`#${MODAL_ID}-raise`);
    const statusEl = root.querySelector(`#${MODAL_ID}-status`);
    const saveBtn = root.querySelector('[data-action="save"]');
    const cancelBtn = root.querySelector('[data-action="cancel"]');
    const closeButtons = root.querySelectorAll('[data-action="close"]');

    const state = {
      root,
      baseInput,
      raiseInput,
      statusEl,
      saveBtn,
      cancelBtn,
      closeButtons,
      active: false,
      keyHandler: null,
    };

    const setStatus = function (message, type) {
      state.statusEl.textContent = message || "";
      if (type) {
        state.statusEl.setAttribute("data-state", type);
      } else {
        state.statusEl.removeAttribute("data-state");
      }
    };

    const fillValues = function (data) {
      const calibration = data && data.calibration ? data.calibration : data;
      if (!calibration) {
        return;
      }
      if (typeof calibration.base_angle === "number" && !Number.isNaN(calibration.base_angle)) {
        state.baseInput.value = calibration.base_angle.toFixed(0);
      }
      if (typeof calibration.raise_angle === "number" && !Number.isNaN(calibration.raise_angle)) {
        state.raiseInput.value = calibration.raise_angle.toFixed(0);
      }
    };

    const closeModal = function () {
      if (!state.active) {
        return;
      }
      state.active = false;
      root.classList.remove("is-visible");
      document.body.classList.remove("has-settings-modal");
      setStatus("", null);
      state.saveBtn.disabled = false;
      if (state.keyHandler) {
        document.removeEventListener("keydown", state.keyHandler, true);
        state.keyHandler = null;
      }
    };

    const loadCalibration = function () {
      setStatus("Загрузка…", null);
      state.saveBtn.disabled = true;
      fetchCalibration()
        .then((data) => {
          fillValues(data);
          setStatus("", null);
        })
        .catch((err) => {
          setStatus(`Не удалось загрузить: ${err.message}`, "error");
        })
        .finally(() => {
          state.saveBtn.disabled = false;
          requestAnimationFrame(() => {
            state.baseInput.focus();
          });
        });
    };

    const validate = function () {
      const base = Number(state.baseInput.value);
      const raise = Number(state.raiseInput.value);
      if (!Number.isFinite(base) || !Number.isFinite(raise)) {
        return { ok: false, message: "Введите числовые значения." };
      }
      if (base < 0 || base > 180) {
        return { ok: false, message: "Базовый угол должен быть в диапазоне 0-180°." };
      }
      if (raise < 5 || raise > 180) {
        return { ok: false, message: "Угол подъёма должен быть в диапазоне 5-180°." };
      }
      return { ok: true, base, raise };
    };

    const saveCalibration = function () {
      const result = validate();
      if (!result.ok) {
        setStatus(result.message, "error");
        return;
      }
      setStatus("Сохранение…", null);
      state.saveBtn.disabled = true;
      postCalibration({
        base_angle: result.base,
        raise_angle: result.raise,
      })
        .then((data) => {
          fillValues(data);
          setStatus("Настройки сохранены.", "success");
        })
        .catch((err) => {
          setStatus(err.message || "Не удалось сохранить настройки.", "error");
        })
        .finally(() => {
          state.saveBtn.disabled = false;
        });
    };

    const openModal = function () {
      if (state.active) {
        return;
      }
      state.active = true;
      root.classList.add("is-visible");
      document.body.classList.add("has-settings-modal");
      loadCalibration();
      state.keyHandler = function (event) {
        if (event.key === "Escape") {
          event.preventDefault();
          closeModal();
        }
      };
      document.addEventListener("keydown", state.keyHandler, true);
    };

    state.saveBtn.addEventListener("click", saveCalibration);
    state.cancelBtn.addEventListener("click", closeModal);
    state.closeButtons.forEach((btn) => {
      btn.addEventListener("click", closeModal);
    });
    root.addEventListener("click", (event) => {
      const action = event.target && event.target.getAttribute("data-action");
      if (action === "close") {
        closeModal();
      }
    });

    modalInstance = {
      open: openModal,
      close: closeModal,
      setStatus,
      fillValues,
    };
    return modalInstance;
  }

  function ensureSettingsCard() {
    if (document.getElementById(CARD_ID)) {
      return true;
    }
    const column = findSettingsColumn();
    if (!column) {
      return false;
    }
    const card = document.createElement("div");
    card.id = CARD_ID;
    card.className = "v-sheet v-sheet--outlined theme--dark mod-sheet settings-card";
    card.innerHTML = `
      <p class="mod-title">Настройки</p>
      <div class="mod-wrapper">
        <div class="status-wrapper settings-wrapper">
          <button type="button" class="settings-chip" data-action="open-calibration">
            <span class="chip-title">Калибровка</span>
            <span class="chip-value">Плечо · открыть</span>
          </button>
        </div>
      </div>
    `;
    column.appendChild(card);
    const button = card.querySelector('[data-action="open-calibration"]');
    if (button) {
      button.addEventListener("click", () => {
        const modal = getModalInstance();
        modal.open();
      });
    }
    return true;
  }

  function init() {
    if (ensureSettingsCard()) {
      return;
    }
    const observer = new MutationObserver(() => {
      if (ensureSettingsCard()) {
        observer.disconnect();
      }
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }

  onReady(init);
})();
