/* global Chart */

(function () {
  const elements = {
    connectionIndicator: document.getElementById('connection-indicator'),
    connectionLabel: document.getElementById('connection-label'),
    reconnectButton: document.getElementById('reconnect-button'),
    batteryPercent: document.getElementById('battery-percent'),
    batteryVoltage: document.getElementById('battery-voltage'),
    cpuUsage: document.getElementById('cpu-usage'),
    cpuTemp: document.getElementById('cpu-temp'),
    ramUsage: document.getElementById('ram-usage'),
    speedValue: document.getElementById('speed-value'),
    connectionQuality: document.getElementById('connection-quality'),
    gyro: {
      x: document.getElementById('gyro-x'),
      y: document.getElementById('gyro-y'),
      z: document.getElementById('gyro-z')
    },
    accel: {
      x: document.getElementById('accel-x'),
      y: document.getElementById('accel-y'),
      z: document.getElementById('accel-z')
    },
    speedSlider: document.getElementById('speed-slider'),
    cvflL1: document.getElementById('cvfl-l1'),
    cvflL2: document.getElementById('cvfl-l2'),
    cvflSp: document.getElementById('cvfl-sp'),
    cvflToggle: document.getElementById('cvfl-toggle'),
    cvflColorToggle: document.getElementById('cvfl-color-toggle'),
    cvflColorLabel: document.getElementById('cvfl-color-label'),
    fcToggle: document.getElementById('fc-toggle'),
    fcColor: document.getElementById('fc-color'),
    actionButtons: Array.from(document.querySelectorAll('.action-toggle')),
    modeButtons: Array.from(document.querySelectorAll('.mode-toggle')),
    activeModeButton: document.querySelector('.mode-toggle[data-mode="ACTIVE"]'),
    movementButtons: Array.from(document.querySelectorAll('.pad-button')),
    utilities: Array.from(document.querySelectorAll('.secondary-button[data-command]')),
    videoImage: document.getElementById('video-stream'),
    videoRefresh: document.getElementById('refresh-video'),
    cameraHqToggle: document.getElementById('camera-hq-toggle'),
    distanceBadge: document.getElementById('distance-overlay'),
    distanceStatusValue: document.getElementById('distance-status-value'),
    distanceStatusLabel: document.getElementById('distance-status-label'),
    distanceSettingsButton: document.getElementById('distance-settings-button'),
    distanceSettingsPanel: document.getElementById('distance-settings-panel'),
    distanceToggle: document.getElementById('distance-toggle'),
    stripButton: document.querySelector('[data-light="strip"]'),
    calibrationModal: document.getElementById('calibration-modal'),
    calibrationBase: document.getElementById('calibration-base'),
    calibrationRaise: document.getElementById('calibration-raise'),
    calibrationStatus: document.getElementById('calibration-status'),
    calibrationSave: document.getElementById('calibration-save'),
    calibrationVoltage: document.getElementById('calibration-voltage'),
    calibrationRun: document.getElementById('calibration-run'),
    openCalibration: document.getElementById('open-calibration')
  };

  const BATTERY_MIN_VOLTAGE = 6.8;
  const BATTERY_MAX_VOLTAGE = 8.4;

  const state = {
    ws: null,
    eventSource: null,
    connected: false,
    reconnectTimer: null,
    batteryHistory: Array(60).fill(0),
    cpuHistory: Array(60).fill(0),
    charts: {
      battery: null,
      cpu: null
    },
    batteryMeta: { scale: BATTERY_MAX_VOLTAGE, min_voltage: BATTERY_MIN_VOLTAGE, max_voltage: BATTERY_MAX_VOLTAGE },
    speed: parseInt(elements.speedSlider?.value || '100', 10),
    speedDebounce: null,
    connectionQualityClass: 'text-white/70',
    lastInfoReceived: null,
    qualityInterval: null,
    actionStates: Object.create(null),
    cvflActive: false,
    cvflColorOn: true,
    fcActive: false,
    pressedKeys: Object.create(null),
    movementButtons: [],
    armClusters: [],
    movementKeyMap: Object.create(null),
    batterySmooth: {
      window: [],
      ema: null,
      last: null
    },
    shoulderCalibration: null,
    systemMode: 'ACTIVE',
    cameraHighQuality: false,
    cameraMeta: null,
    lights: {
      stripAvailable: true
    },
    distanceStatus: 'disabled',
    gradient: {
      dark: { instance: null, currentState: null },
      eco: { instance: null, currentState: null }
    },
    reloadVideoStream: null
  };

  const armMappings = [
    { label: 'Gripper', command: 'grab', stop: 'GLstop', alt: 'loose', icons: { primary: 'arrow_upward', secondary: 'arrow_downward' } },
    { label: 'Shoulder', command: 'armUp', stop: 'armStop', alt: 'armDown', icons: { primary: 'arrow_upward', secondary: 'arrow_downward' } },
    { label: 'Wrist', command: 'handUp', stop: 'handStop', alt: 'handDown', icons: { primary: 'expand_less', secondary: 'expand_more' } },
    { label: 'Rotate', command: 'lookleft', stop: 'LRstop', alt: 'lookright', icons: { primary: 'arrow_back', secondary: 'arrow_forward' } },
    { label: 'Camera', command: 'up', stop: 'UDstop', alt: 'down', icons: { primary: 'arrow_upward', secondary: 'arrow_downward' } }
  ];

  const QUALITY_DEFAULT_CLASS = 'text-white/70';

  function smoothVoltage (value) {
    if (!Number.isFinite(value)) {
      return state.batterySmooth.last;
    }
    const bucket = state.batterySmooth;
    bucket.window.push(value);
    if (bucket.window.length > 7) {
      bucket.window.shift();
    }
    const sorted = bucket.window.slice().sort((a, b) => a - b);
    const median = sorted[Math.floor(sorted.length / 2)];
    if (bucket.ema === null) {
      bucket.ema = median;
    } else {
      const alpha = 0.3;
      bucket.ema = alpha * median + (1 - alpha) * bucket.ema;
    }
    let candidate = bucket.ema;
    if (bucket.last !== null) {
      const maxDelta = 0.05;
      const delta = candidate - bucket.last;
      if (Math.abs(delta) > maxDelta) {
        candidate = bucket.last + Math.sign(delta) * maxDelta;
      }
    }
    bucket.last = candidate;
    return candidate;
  }

  
  function voltageToPercent (voltage) {
    if (!Number.isFinite(voltage)) {
      return null;
    }
    const maxVoltage = Number(
      state.batteryMeta?.max_voltage ??
      state.batteryMeta?.scale ??
      BATTERY_MAX_VOLTAGE
    );
    const minVoltage = Number(state.batteryMeta?.min_voltage ?? BATTERY_MIN_VOLTAGE);
    const span = maxVoltage - minVoltage;
    if (span <= 0) {
      return null;
    }
    const pct = ((voltage - minVoltage) / span) * 100;
    return Math.max(0, Math.min(100, pct));
  }

  function init () {
    loadBatteryMetadata();
    setupCharts();
    setupVideo();
    setupGradientBackground();
    setupParallaxBackground();
    setupActionButtons();
    setupModeControls();
    setupMovementControls();
    setupSpeedControl();
    setupCvflControls();
    setupFcControls();
    setupArmControls();
    setupUtilities();
    setupCalibration();
    setupWebSocket();
    setupEvents();
    setupDistanceSettings();
    setupConnectionQualityMonitor();
    startInfoPolling();
    updateConnection(false);
  }

  function setupCharts () {
    const common = {
      type: 'line',
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        plugins: {
          legend: { display: false },
          tooltip: { enabled: false }
        },
        scales: {
          x: { display: false },
          y: { display: false, beginAtZero: true, min: 0, max: 100 }
        },
        elements: {
          line: { borderWidth: 2, tension: 0.35 },
          point: { radius: 0 }
        }
      }
    };

    const batteryCtx = document.getElementById('battery-chart')?.getContext('2d');
    if (batteryCtx) {
      state.charts.battery = new Chart(batteryCtx, {
        ...common,
        data: {
          labels: Array(state.batteryHistory.length).fill(''),
          datasets: [{
            data: [...state.batteryHistory],
            borderColor: '#1173d4',
            backgroundColor: 'rgba(17, 115, 212, 0.12)',
            fill: true
          }]
        }
      });
    }

    const cpuCtx = document.getElementById('cpu-chart')?.getContext('2d');
    if (cpuCtx) {
      state.charts.cpu = new Chart(cpuCtx, {
        ...common,
        data: {
          labels: Array(state.cpuHistory.length).fill(''),
          datasets: [{
            data: [...state.cpuHistory],
            borderColor: '#16a34a',
            backgroundColor: 'rgba(22, 163, 74, 0.15)',
            fill: true
          }]
        }
      });
    }
  }

  function loadBatteryMetadata () {
    fetch('/api/calibration', { credentials: 'same-origin' })
      .then((res) => res.ok ? res.json() : Promise.reject(new Error(`HTTP ${res.status}`)))
      .then((data) => {
        const incoming = (data && typeof data.calibration === 'object')
          ? data.calibration
          : (typeof data === 'object' && data ? data : null);
        if (incoming) {
          state.batteryMeta = {
            ...state.batteryMeta,
            ...incoming
          };
        }
        const displayScale = Number(
          state.batteryMeta?.scale ??
          state.batteryMeta?.max_voltage ??
          BATTERY_MAX_VOLTAGE
        );
        if (elements.calibrationVoltage && Number.isFinite(displayScale)) {
          elements.calibrationVoltage.placeholder = displayScale.toFixed(2);
        }
      })
      .catch(() => {
        state.batteryMeta = state.batteryMeta || {
          scale: BATTERY_MAX_VOLTAGE,
          max_voltage: BATTERY_MAX_VOLTAGE,
          min_voltage: BATTERY_MIN_VOLTAGE
        };
      });
  }

  function setupVideo () {
    if (!elements.videoImage) {
      return;
    }
    const assignSource = (fresh) => {
      const url = fresh ? `/video_feed?rand=${Date.now()}` : '/video_feed';
      elements.videoImage.src = url;
    };
    state.reloadVideoStream = assignSource;
    assignSource(true);
    elements.videoImage.addEventListener('error', () => {
      window.setTimeout(() => assignSource(true), 2000);
    });
    if (elements.videoRefresh) {
      elements.videoRefresh.addEventListener('click', () => {
        assignSource(true);
      });
    }
  }

  function setupActionButtons () {
    elements.actionButtons.forEach((btn) => {
      const cmd = btn.dataset.action;
      const off = btn.dataset.off;
      state.actionStates[cmd] = false;
      btn.addEventListener('click', () => {
        if (btn.disabled) return;
        const active = !state.actionStates[cmd];
        state.actionStates[cmd] = active;
        btn.classList.toggle('is-active', active);
        sendCommand(active ? cmd : off);
      });
    });
  }

  function setupModeControls () {
    elements.modeButtons.forEach((btn) => {
      btn.addEventListener('click', () => {
        if (btn.disabled) return;
        const target = (btn.dataset.mode || '').toUpperCase();
        if (target) {
          state.systemMode = target;
          updateModeButtons();
        }
        const command = btn.dataset.command;
        if (command) {
          sendCommand(command);
        }
      });
    });

    if (elements.cameraHqToggle) {
      elements.cameraHqToggle.addEventListener('click', () => {
        if (elements.cameraHqToggle.disabled) return;
        const enable = !state.cameraHighQuality;
        state.cameraHighQuality = enable;
        updateHdToggle();
        updateGradientTheme();
        sendCommand(enable ? 'cameraHQOn' : 'cameraHQOff');
        state.reloadVideoStream?.(true);
      });
    }

    updateModeButtons();
  }

  function setupMovementControls () {
    state.movementKeyMap = Object.create(null);
    state.movementButtons = elements.movementButtons.map((btn) => {
      const command = btn.dataset.command;
      const stop = btn.dataset.stop;
      const keys = (btn.dataset.keys || btn.dataset.key || '')
        .split(',')
        .map((code) => code.trim())
        .filter(Boolean);

      const entry = {
        btn,
        command,
        stop,
        keys
      };

      entry.press = () => {
        btn.classList.add('is-active');
        sendCommand(command);
      };

      entry.release = () => {
        btn.classList.remove('is-active');
        if (stop) {
          sendCommand(stop);
        }
      };

      const pointerDown = (evt) => {
        evt.preventDefault();
        entry.press();
        const upListener = () => {
          entry.release();
          document.removeEventListener('pointerup', upListener);
          document.removeEventListener('pointercancel', upListener);
          document.removeEventListener('pointerleave', upListener);
        };
        document.addEventListener('pointerup', upListener, { once: true });
        document.addEventListener('pointercancel', upListener, { once: true });
        document.addEventListener('pointerleave', upListener, { once: true });
      };

      btn.addEventListener('pointerdown', pointerDown);

      keys.forEach((code) => {
        state.movementKeyMap[code] = entry;
      });

      return entry;
    });

    window.addEventListener('keydown', (event) => {
      const entry = state.movementKeyMap[event.code];
      if (!entry || state.pressedKeys[event.code]) {
        return;
      }
      state.pressedKeys[event.code] = entry;
      entry.press();
    });

    window.addEventListener('keyup', (event) => {
      const entry = state.movementKeyMap[event.code];
      if (!entry) return;
      if (state.pressedKeys[event.code]) {
        delete state.pressedKeys[event.code];
        entry.release();
      }
    });
  }

  function setupSpeedControl () {
    if (!elements.speedSlider) {
      return;
    }
    const update = () => {
      const value = parseInt(elements.speedSlider.value, 10);
      if (Number.isNaN(value)) return;
      state.speed = value;
      elements.speedValue.textContent = value;
      if (state.speedDebounce) {
        window.clearTimeout(state.speedDebounce);
      }
      state.speedDebounce = window.setTimeout(() => {
        sendCommand(`wsB ${state.speed}`);
      }, 200);
    };
    elements.speedSlider.addEventListener('input', update);
    update();
  }

  function setupCvflControls () {
    if (elements.cvflToggle) {
      elements.cvflToggle.addEventListener('click', () => {
        state.cvflActive = !state.cvflActive;
        elements.cvflToggle.textContent = state.cvflActive ? 'Stop' : 'Start';
        sendCommand(state.cvflActive ? 'CVFL' : 'stopCV');
      });
    }

    if (elements.cvflColorToggle) {
      elements.cvflColorToggle.addEventListener('click', () => {
        state.cvflColorOn = !state.cvflColorOn;
        const next = state.cvflColorOn ? 255 : 0;
        elements.cvflColorLabel.textContent = state.cvflColorOn ? '#FFFFFF' : '#000000';
        sendCommand(`CVFLColorSet ${next}`);
      });
    }

    const sliderHandlers = [
      { el: elements.cvflL1, prefix: 'CVFLL1' },
      { el: elements.cvflL2, prefix: 'CVFLL2' },
      { el: elements.cvflSp, prefix: 'CVFLSP' }
    ];
    sliderHandlers.forEach(({ el, prefix }) => {
      if (!el) return;
      el.addEventListener('change', () => {
        const value = Math.round(parseFloat(el.value || '0'));
        sendCommand(`${prefix} ${value}`);
      });
    });
  }

  function setupFcControls () {
    if (elements.fcToggle) {
      elements.fcToggle.addEventListener('click', () => {
        state.fcActive = !state.fcActive;
        elements.fcToggle.textContent = state.fcActive ? 'Stop' : 'Start';
        sendCommand(state.fcActive ? 'findColor' : 'stopCV');
      });
    }
    if (elements.fcColor) {
      elements.fcColor.addEventListener('input', (event) => {
        const hex = event.target.value;
        const hsv = rgbToHsv255(hexToRgb(hex));
        sendJson({
          title: 'findColorSet',
          data: hsv
        });
      });
    }
  }

  function setupArmControls () {
    const template = document.getElementById('arm-cluster-template');
    if (!template) return;
    const placeholderClusters = Array.from(document.querySelectorAll('.arm-cluster'));
    placeholderClusters.forEach((placeholder, index) => {
      const mapping = armMappings[index];
      if (!mapping) return;
      const clone = template.content.cloneNode(true);
      const container = clone.querySelector('div');
      container.classList.add('arm-cluster');
      const label = container.querySelector('.cluster-label');
      const primary = container.querySelector('[data-role="primary"]');
      const secondary = container.querySelector('[data-role="secondary"]');
      const primaryIcon = container.querySelector('[data-icon="primary"]');
      const secondaryIcon = container.querySelector('[data-icon="secondary"]');
      label.textContent = mapping.label;
      if (mapping.small) {
        container.dataset.small = 'true';
      }
      if (primaryIcon) {
        primaryIcon.textContent = (mapping.icons && mapping.icons.primary) || 'arrow_upward';
      }
      if (secondaryIcon) {
        secondaryIcon.textContent = (mapping.icons && mapping.icons.secondary) || 'arrow_downward';
      }
      attachArmButton(primary, mapping.command, mapping.stop);
      attachArmButton(secondary, mapping.alt, mapping.stop);
      placeholder.replaceWith(container);
    });
  }

  function attachArmButton (button, command, stop) {
    let active = false;
    let fallbackTimer = null;

    const clearFallback = () => {
      if (fallbackTimer !== null) {
        window.clearTimeout(fallbackTimer);
        fallbackTimer = null;
      }
    };

    const scheduleFallback = () => {
      clearFallback();
      fallbackTimer = window.setTimeout(() => {
        if (active) {
          active = false;
          button.classList.remove('is-active');
          sendCommand(stop);
        }
      }, 1200);
    };

    const sendStop = () => {
      if (!active) return;
      active = false;
      button.classList.remove('is-active');
      clearFallback();
      sendCommand(stop);
    };

    const pointerDown = (evt) => {
      evt.preventDefault();
      if (!active) {
        active = true;
        button.classList.add('is-active');
        sendCommand(command);
      }
      scheduleFallback();
      const release = () => {
        document.removeEventListener('pointerup', release);
        document.removeEventListener('pointercancel', release);
        document.removeEventListener('pointerleave', release);
        sendStop();
      };
      document.addEventListener('pointerup', release, { once: true });
      document.addEventListener('pointercancel', release, { once: true });
      document.addEventListener('pointerleave', release, { once: true });
    };

    button.addEventListener('pointerdown', pointerDown);
  }

  function setupUtilities () {
    elements.utilities.forEach((btn) => {
      const command = btn.dataset.command;
      const off = btn.dataset.off;
      if (off) {
        btn.dataset.state = 'off';
        btn.addEventListener('click', () => {
          const active = btn.dataset.state !== 'on';
          btn.dataset.state = active ? 'on' : 'off';
          btn.classList.toggle('is-active', active);
          sendCommand(active ? command : off);
        });
      } else {
        btn.addEventListener('click', () => sendCommand(command));
      }
    });
  }

  function setupCalibration () {
    if (!elements.openCalibration || !elements.calibrationModal) return;

    const closeModal = () => {
      elements.calibrationModal.classList.add('hidden');
    };

    elements.openCalibration.addEventListener('click', async () => {
      elements.calibrationStatus.textContent = 'Loading...';
      elements.calibrationStatus.classList.remove('text-red-400', 'text-green-400');
      elements.calibrationModal.classList.remove('hidden');
      try {
        const [shoulderRes, batteryRes] = await Promise.all([
          fetch('/api/servo/shoulder', { credentials: 'same-origin' }),
          fetch('/api/calibration', { credentials: 'same-origin' })
        ]);
        if (!shoulderRes.ok) {
          throw new Error(`Shoulder HTTP ${shoulderRes.status}`);
        }
        const shoulderData = await shoulderRes.json();
        const shoulderCalibration = shoulderData?.calibration || shoulderData;
        if (shoulderCalibration) {
          state.shoulderCalibration = { ...shoulderCalibration };
          elements.calibrationBase.value = Number(shoulderCalibration.base_angle || 0).toFixed(0);
          elements.calibrationRaise.value = Number(shoulderCalibration.raise_angle || 180).toFixed(0);
        }
        if (batteryRes.ok) {
          const batteryData = await batteryRes.json();
          if (batteryData && typeof batteryData.voltage === 'number') {
            elements.calibrationVoltage.placeholder = batteryData.voltage.toFixed(2);
          }
          if (batteryData && typeof batteryData.calibration === 'object') {
            state.batteryMeta = {
              ...state.batteryMeta,
              ...batteryData.calibration
            };
          }
        }
        if (elements.calibrationVoltage) {
          elements.calibrationVoltage.value = '';
        }
        elements.calibrationStatus.textContent = '';
      } catch (error) {
        elements.calibrationStatus.textContent = error.message;
        elements.calibrationStatus.classList.add('text-red-400');
      }
    });

    elements.calibrationModal.querySelectorAll('[data-close]').forEach((btn) => {
      btn.addEventListener('click', closeModal);
    });

    elements.calibrationRun?.addEventListener('click', async () => {
      const value = parseFloat(elements.calibrationVoltage?.value || '0');
      if (!Number.isFinite(value) || value <= 0) {
        elements.calibrationStatus.textContent = 'Enter a valid measured voltage.';
        elements.calibrationStatus.classList.add('text-red-400');
        elements.calibrationStatus.classList.remove('text-green-400');
        return;
      }
      elements.calibrationStatus.textContent = 'Calibrating...';
      elements.calibrationStatus.classList.remove('text-red-400', 'text-green-400');
      try {
        const response = await fetch('/api/calibration', {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ voltage: value })
        });
        const data = await response.json();
        if (!response.ok || data?.error) {
          throw new Error(data?.error || `HTTP ${response.status}`);
        }
        elements.calibrationStatus.textContent = 'Voltage calibration saved.';
        elements.calibrationStatus.classList.add('text-green-400');
        elements.calibrationStatus.classList.remove('text-red-400');
        if (elements.batteryVoltage && typeof data.voltage === 'number') {
          elements.batteryVoltage.textContent = Number(data.voltage).toFixed(2);
        }
        if (elements.calibrationVoltage) {
          elements.calibrationVoltage.value = '';
          if (data && typeof data.calibration === 'object') {
            state.batteryMeta = {
              ...state.batteryMeta,
              ...data.calibration
            };
          }
          const displayScale = Number(
            state.batteryMeta?.scale ??
            state.batteryMeta?.max_voltage ??
            BATTERY_MAX_VOLTAGE
          );
          if (Number.isFinite(displayScale)) {
            elements.calibrationVoltage.placeholder = displayScale.toFixed(2);
          }
        }
        sendCommand('get_info');
      } catch (error) {
        elements.calibrationStatus.textContent = error.message;
        elements.calibrationStatus.classList.add('text-red-400');
        elements.calibrationStatus.classList.remove('text-green-400');
      }
    });

    elements.calibrationSave?.addEventListener('click', async () => {
      const base = Number(elements.calibrationBase.value);
      const raise = Number(elements.calibrationRaise.value);
      if (!Number.isFinite(base) || base < 0 || base > 180) {
        elements.calibrationStatus.textContent = 'Base angle must be between 0 and 180.';
        elements.calibrationStatus.classList.add('text-red-400');
        return;
      }
      if (!Number.isFinite(raise) || raise < 5 || raise > 180) {
        elements.calibrationStatus.textContent = 'Raise angle must be between 5 and 180.';
        elements.calibrationStatus.classList.add('text-red-400');
        return;
      }
      elements.calibrationStatus.textContent = 'Saving...';
      elements.calibrationStatus.classList.remove('text-red-400', 'text-green-400');
      try {
        const response = await fetch('/api/servo/shoulder', {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ base_angle: base, raise_angle: raise })
        });
        const data = await response.json();
        if (!response.ok || data?.error) {
          throw new Error(data?.error || `HTTP ${response.status}`);
        }
        elements.calibrationStatus.textContent = 'Calibration saved.';
        elements.calibrationStatus.classList.add('text-green-400');
        window.setTimeout(closeModal, 1200);
      } catch (error) {
        elements.calibrationStatus.textContent = error.message;
        elements.calibrationStatus.classList.add('text-red-400');
      }
    });
  }

  function setupWebSocket () {
    if (state.connectFn) {
      state.connectFn();
      return;
    }

    const connect = () => {
      if (state.ws && (state.ws.readyState === WebSocket.OPEN || state.ws.readyState === WebSocket.CONNECTING)) {
        try { state.ws.close(); } catch (err) {}
      }
      const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
      const ws = new WebSocket(`${scheme}://${window.location.host}/ws`);
      state.ws = ws;

      ws.addEventListener('open', () => {
        state.lastInfoReceived = null;
        updateConnection(true);
        sendRaw('admin:123456');
      });

      ws.addEventListener('message', (event) => {
        handleMessage(event.data);
      });

      ws.addEventListener('close', () => {
        state.lastInfoReceived = null;
        updateConnection(false);
        scheduleReconnect();
      });

      ws.addEventListener('error', () => {
        try { ws.close(); } catch (err) {}
      });
    };

    state.connectFn = connect;
    elements.reconnectButton?.addEventListener('click', connect);
    connect();
  }

  function setupEvents () {
    if (!window.EventSource) return;
    if (state.eventSource) {
      try { state.eventSource.close(); } catch (err) {}
      state.eventSource = null;
    }
    try {
      const source = new EventSource('/api/events');
      state.eventSource = source;
      source.addEventListener('distance_update', (event) => {
        try {
          const payload = JSON.parse(event.data || '{}');
          updateDistanceOverlay(payload.cm, payload.display, payload.status);
        } catch (error) {
          console.warn('distance_update parse failed', error);
        }
      });
      source.addEventListener('error', () => {
        try { source.close(); } catch (err) {}
        if (state.eventSource === source) {
          state.eventSource = null;
        }
        window.setTimeout(setupEvents, 3000);
      });
    } catch (error) {
      console.warn('Failed to establish SSE stream', error);
    }
  }

  function updateConnection (connected) {
    state.connected = connected;
    if (connected) {
      elements.connectionIndicator.textContent = 'wifi';
      elements.connectionIndicator.classList.remove('text-red-500');
      elements.connectionIndicator.classList.add('text-green-400');
      elements.connectionLabel.textContent = 'Connected';
      elements.reconnectButton?.classList.add('hidden');
    } else {
      elements.connectionIndicator.textContent = 'wifi_off';
      elements.connectionIndicator.classList.add('text-red-500');
      elements.connectionIndicator.classList.remove('text-green-400');
      elements.connectionLabel.textContent = 'Disconnected';
      elements.reconnectButton?.classList.remove('hidden');
    }
    updateConnectionQuality();
  }

  function scheduleReconnect () {
    if (state.reconnectTimer || !state.connectFn) return;
    state.reconnectTimer = window.setTimeout(() => {
      state.reconnectTimer = null;
      state.connectFn();
    }, 2000);
  }

  function handleMessage (raw) {
    if (!raw) return;
    let payload = null;
    try {
      payload = JSON.parse(raw);
    } catch (error) {
      return;
    }
    if (payload?.title === 'get_info') {
      applyStats(payload);
      state.lastInfoReceived = Date.now();
      updateConnectionQuality();
    }
  }

  function updateDistanceOverlay (cm, display, status) {
    const resolvedStatus = status || state.distanceStatus || 'disabled';
    state.distanceStatus = resolvedStatus;
    const numericValue = Number.isFinite(cm) ? Number(cm) : null;
    const displayValue = (typeof display === 'number' && Number.isFinite(display))
      ? Number(display).toFixed(1)
      : (typeof display === 'string' ? display : '--');
    let badgeText = 'Distance - -- cm';
    let statValue = '--';
    if (resolvedStatus !== 'disabled') {
      if (numericValue !== null) {
        const formatted = numericValue.toFixed(1);
        badgeText = `Distance - ${formatted} cm`;
        statValue = formatted;
      } else if (displayValue && displayValue !== '--') {
        badgeText = `Distance - ${displayValue} cm`;
        statValue = displayValue;
      }
    }
    if (elements.distanceBadge) {
      elements.distanceBadge.textContent = badgeText;
    }
    if (elements.distanceStatusValue) {
      elements.distanceStatusValue.textContent = statValue;
    }
    if (elements.distanceStatusLabel) {
      elements.distanceStatusLabel.textContent = formatDistanceStatus(resolvedStatus);
    }
    syncDistanceToggle(resolvedStatus);
  }

  function formatDistanceStatus (status) {
    switch (status) {
      case 'active':
        return 'Active';
      case 'paused':
        return 'Paused';
      case 'disabled':
        return 'Disabled';
      default:
        return 'Unknown';
    }
  }

  function syncDistanceToggle (status) {
    const toggle = elements.distanceToggle;
    if (!toggle) return;
    const shouldEnable = status && status !== 'disabled';
    if (toggle.checked !== shouldEnable) {
      toggle.checked = shouldEnable;
    }
    state.actionStates.distanceMonitorOn = shouldEnable;
    toggle.disabled = false;
  }

  function setupDistanceSettings () {
    const btn = elements.distanceSettingsButton;
    const panel = elements.distanceSettingsPanel;
    const toggle = elements.distanceToggle;
    if (!btn || !panel) return;

    const closePanel = () => panel.classList.add('hidden');
    const togglePanel = (evt) => {
      evt?.stopPropagation();
      panel.classList.toggle('hidden');
    };

    btn.addEventListener('click', togglePanel);
    panel.addEventListener('click', (evt) => evt.stopPropagation());
    document.addEventListener('click', closePanel);

    if (toggle) {
      toggle.addEventListener('change', () => {
        toggle.disabled = true;
        const enabled = toggle.checked;
        sendCommand(enabled ? 'distanceMonitorOn' : 'distanceMonitorOff');
      });
    }
  }

  function applyStats (payload) {
    const data = payload.data || [];
    const battery = payload.battery || {};
    const gyro = payload.gyro || {};
    const accel = payload.accel || {};
    const distance = payload.distance || {};
    const cpuTemp = data[0];
    const cpuUsage = data[1];
    const ramUsage = data[2];
    const rawVoltageCandidates = [
      typeof battery.voltage === 'number' ? battery.voltage : null,
      parseFloat(battery.voltage_display),
      parseFloat(data[3])
    ];
    const rawVoltage = rawVoltageCandidates.find((value) => Number.isFinite(value));
    const smoothedVoltage = smoothVoltage(rawVoltage);
    const percentFromVoltage = smoothedVoltage != null ? voltageToPercent(smoothedVoltage) : null;
    const fallbackVoltageStr = (battery.voltage_display && battery.voltage_display !== 'N/A') ? battery.voltage_display : sanitizeNumber(data[3]);
    let percentValue = Number.isFinite(percentFromVoltage) ? percentFromVoltage : null;
    if (percentValue === null) {
      const percentCandidates = [battery.percentage, battery.percentage_display, data[4]];
      for (const candidate of percentCandidates) {
        const parsed = parseFloat(candidate);
        if (Number.isFinite(parsed)) {
          percentValue = parsed;
          break;
        }
      }
    }

    if (elements.cpuTemp) elements.cpuTemp.textContent = sanitizeNumber(cpuTemp);
    if (elements.cpuUsage) elements.cpuUsage.textContent = sanitizeNumber(cpuUsage);
    if (elements.ramUsage) elements.ramUsage.textContent = sanitizeNumber(ramUsage);
    if (elements.batteryVoltage) {
      if (smoothedVoltage != null) {
        elements.batteryVoltage.textContent = smoothedVoltage.toFixed(2);
      } else {
        elements.batteryVoltage.textContent = fallbackVoltageStr || '--';
      }
    }
    if (elements.batteryPercent) {
      if (percentValue !== null) {
        elements.batteryPercent.textContent = Math.round(percentValue);
      } else if (battery.percentage_display && battery.percentage_display !== 'N/A') {
        elements.batteryPercent.textContent = battery.percentage_display;
      } else {
        elements.batteryPercent.textContent = '--';
      }
    }

    updateAxis(elements.gyro, gyro);
    updateAxis(elements.accel, accel);

    if (state.charts.battery) {
      pushChartValue(state.batteryHistory, percentValue, state.charts.battery);
    }
    if (state.charts.cpu) {
      pushChartValue(state.cpuHistory, parseFloat(cpuUsage || '0'), state.charts.cpu);
    }

    updateLightingCapabilities(payload.lights);
    syncModeState(payload);

    updateDistanceOverlay(distance.cm, distance.display, distance.status);
  }

  function syncModeState (payload) {
    if (!payload) return;
    const cameraMeta = payload.camera || null;
    const reportedMode = (payload.mode || (cameraMeta && cameraMeta.mode) || state.systemMode || '').toUpperCase();
    if (reportedMode) {
      state.systemMode = reportedMode;
    }
    if (cameraMeta) {
      state.cameraHighQuality = Boolean(cameraMeta.high_quality);
      state.cameraMeta = cameraMeta;
    }
    updateModeButtons();
  }

  function updateModeButtons () {
    const mode = (state.systemMode || '').toUpperCase();
    const visualMode = mode === 'STANDBY' ? 'ACTIVE' : mode;
    elements.modeButtons.forEach((btn) => {
      const target = (btn.dataset.mode || '').toUpperCase();
      const isActive = Boolean(visualMode && target === visualMode);
      btn.classList.toggle('is-active', isActive);
      btn.setAttribute('aria-pressed', isActive ? 'true' : 'false');
    });
    updateHdToggle();
    updateActiveStandbyLabel(mode);
    updateEcoTheme(mode === 'ECO');
    updateGradientTheme();
  }

  function updateActiveStandbyLabel (mode) {
    const btn = elements.activeModeButton;
    if (!btn) return;
    const isStandby = mode === 'STANDBY';
    const activeLabel = btn.dataset.labelActive || 'Active';
    const standbyLabel = btn.dataset.labelStandby || 'Standby';
    const nextLabel = isStandby ? standbyLabel : activeLabel;
    if (btn.textContent !== nextLabel) {
      btn.textContent = nextLabel;
    }
    btn.setAttribute('title', isStandby ? 'Standby mode (auto)' : 'Active mode');
  }

  function updateEcoTheme (enabled) {
    const body = document.body;
    if (!body) return;
    body.classList.toggle('eco-mode', Boolean(enabled));
  }

  function setupGradientBackground () {
    if (typeof window.Granim !== 'function') return;
    const darkCanvas = document.getElementById('bg-dark');
    if (darkCanvas) {
      state.gradient.dark.instance = new window.Granim({
        element: '#bg-dark',
        direction: 'diagonal',
        isPausedWhenNotInView: true,
        stateTransitionSpeed: 900,
        states: {
          'dark-default': {
            gradients: [
              ['#000000', '#0d0f12'],
              ['#0f1015', '#15202c'],
              ['#101722', '#1a2533'],
              ['#162031', '#223649']
            ],
            transitionSpeed: 10000
          },
          'dark-accent': {
            gradients: [
              ['#05060a', '#15202c'],
              ['#0d0f12', '#1c2b3d'],
              ['#101722', '#26394f']
            ],
            transitionSpeed: 14000
          }
        }
      });
    }
    const ecoCanvas = document.getElementById('bg-eco');
    if (ecoCanvas) {
      state.gradient.eco.instance = new window.Granim({
        element: '#bg-eco',
        direction: 'diagonal',
        isPausedWhenNotInView: true,
        stateTransitionSpeed: 900,
        states: {
          'eco-default': {
            gradients: [
              ['#D4FBCF', '#9EF0B3'],
              ['#B2F2B0', '#72E2B5'],
              ['#C8FCD6', '#4DD6C0'],
              ['#D7FBE8', '#60E0D0'],
              ['#E3FFD5', '#8FFBC2'],
              ['#C6F6D3', '#59E7D9']
            ],
            transitionSpeed: 5000
          },
          'eco-breath': {
            gradients: [
              ['#C6F6D3', '#59E7D9'],
              ['#E3FFD5', '#8FFBC2'],
              ['#D7FBE8', '#60E0D0'],
              ['#C8FCD6', '#4DD6C0']
            ],
            transitionSpeed: 7000
          }
        }
      });
    }
    updateGradientTheme();
  }

  function updateGradientTheme () {
    const mode = (state.systemMode || '').toUpperCase();
    const ecoMode = mode === 'ECO';
    const palette = ecoMode ? state.gradient.eco : state.gradient.dark;
    if (!palette || !palette.instance) return;
    let target = ecoMode ? 'eco-default' : 'dark-default';
    if (!ecoMode && state.cameraHighQuality) {
      target = 'dark-accent';
    } else if (ecoMode && state.cameraHighQuality) {
      target = 'eco-breath';
    }
    if (palette.currentState === target) return;
    try {
      window.requestAnimationFrame(() => {
        palette.instance.changeState(target);
        palette.currentState = target;
      });
    } catch (error) {}
  }

  function setupParallaxBackground () {
    const stages = Array.from(document.querySelectorAll('.bg-stage'));
    if (!stages.length) return;
    const strength = 12;
    const updateTransform = (event) => {
      const { innerWidth, innerHeight } = window;
      const relX = (event.clientX / innerWidth) - 0.5;
      const relY = (event.clientY / innerHeight) - 0.5;
      stages.forEach((stage, index) => {
        const depth = (index + 1) * 0.6;
        const offsetX = -(relX * strength) / depth;
        const offsetY = -(relY * strength) / depth;
        stage.style.transform = `translate3d(${offsetX}px, ${offsetY}px, 0)`;
      });
    };
    window.addEventListener('pointermove', updateTransform);
  }

  function updateHdToggle () {
    const button = elements.cameraHqToggle;
    if (!button) return;
    const inActiveMode = (state.systemMode || '').toUpperCase() === 'ACTIVE';
    const enabled = inActiveMode && state.cameraHighQuality;
    button.disabled = !inActiveMode;
    button.classList.toggle('is-disabled', !inActiveMode);
    button.classList.toggle('is-active', enabled);
    button.setAttribute('aria-pressed', enabled ? 'true' : 'false');
    button.title = inActiveMode ? '1920×1080 @ 30fps' : 'Доступно только в режиме Active';
    document.body?.classList.toggle('camera-hq', enabled);
  }

  function sanitizeNumber (value) {
    if (value === null || value === undefined || value === 'N/A') return '--';
    if (typeof value === 'string') return value;
    if (typeof value === 'number' && Number.isFinite(value)) {
      return value.toFixed(1);
    }
    return '--';
  }

  function updateAxis (slots, data) {
    if (!slots) return;
    if (slots.x) slots.x.textContent = formatAxisValue(data.x);
    if (slots.y) slots.y.textContent = formatAxisValue(data.y);
    if (slots.z) slots.z.textContent = formatAxisValue(data.z);
  }

  function formatAxisValue (value) {
    const num = parseFloat(value);
    if (!Number.isFinite(num)) return '--';
    if (Math.abs(num) >= 10) return num.toFixed(1);
    return num.toFixed(2);
  }

  function pushChartValue (history, value, chart) {
    if (!Number.isFinite(value)) return;
    history.push(value);
    if (history.length > 60) history.shift();
    chart.data.datasets[0].data = [...history];
    chart.update('none');
  }

  function setupConnectionQualityMonitor () {
    updateConnectionQuality();
    if (state.qualityInterval) {
      window.clearInterval(state.qualityInterval);
    }
    state.qualityInterval = window.setInterval(updateConnectionQuality, 2000);
  }

  function updateConnectionQuality () {
    const el = elements.connectionQuality;
    if (!el) return;
    let label = '--';
    let nextClass = QUALITY_DEFAULT_CLASS;

    if (!state.connected) {
      label = 'Offline';
      nextClass = 'text-red-400';
    } else if (!state.lastInfoReceived) {
      label = 'Connecting';
    } else {
      const age = Date.now() - state.lastInfoReceived;
      if (age <= 6000) {
        label = 'Excellent';
        nextClass = 'text-green-400';
      } else if (age <= 12000) {
        label = 'Good';
        nextClass = 'text-emerald-300';
      } else if (age <= 20000) {
        label = 'Weak';
        nextClass = 'text-amber-300';
      } else {
        label = 'Degraded';
        nextClass = 'text-red-400';
      }
    }

    if (state.connectionQualityClass && state.connectionQualityClass !== nextClass) {
      el.classList.remove(state.connectionQualityClass);
    }
    if (!el.classList.contains(nextClass)) {
      el.classList.add(nextClass);
    }
    state.connectionQualityClass = nextClass;
    el.textContent = label;
  }

  function updateLightingCapabilities (lights) {
    const stripBtn = elements.stripButton;
    if (!stripBtn) return;
    const available = !(lights && lights.strip_available === false);
    stripBtn.disabled = !available;
    stripBtn.classList.toggle('is-disabled', !available);
    if (!available) {
      const reason = lights?.strip_reason;
      let message = 'LED strip unavailable';
      if (reason === 'unsupported_pi5') {
        message = 'WS2812 LEDs unsupported on Raspberry Pi 5';
      } else if (reason === 'init_failed' || reason === 'init_error') {
        message = 'WS2812 driver init failed';
      }
      stripBtn.title = message;
      stripBtn.classList.remove('is-active');
      state.actionStates[stripBtn.dataset.action] = false;
    } else {
      stripBtn.removeAttribute('title');
    }
    state.lights.stripAvailable = available;
  }

  function startInfoPolling () {
    window.setInterval(() => {
      sendCommand('get_info');
    }, 1000);
  }

  function sendCommand (command) {
    if (!command) return;
    sendRaw(command);
  }

  function sendJson (payload) {
    if (!payload) return;
    try {
      sendRaw(JSON.stringify(payload));
    } catch (error) {
      console.warn('Failed to send JSON payload', error);
    }
  }

  function sendRaw (value) {
    if (!state.ws || state.ws.readyState !== WebSocket.OPEN) return;
    try {
      state.ws.send(value);
    } catch (error) {
      console.warn('Failed to send command', error);
    }
  }

  function hexToRgb (hex) {
    const clean = hex.replace('#', '');
    if (clean.length !== 6) return [255, 255, 255];
    return [
      parseInt(clean.slice(0, 2), 16),
      parseInt(clean.slice(2, 4), 16),
      parseInt(clean.slice(4, 6), 16)
    ];
  }

  function rgbToHsv255 ([r, g, b]) {
    const arr = [r, g, b].slice();
    const max = Math.max(...arr);
    const min = Math.min(...arr);
    let h = 0;
    const v = max / 255;
    const s = max === 0 ? 0 : 1 - (min / max);

    if (max === min) {
      h = 0;
    } else if (max === r && g >= b) {
      h = 60 * ((g - b) / (max - min));
    } else if (max === r && g < b) {
      h = 60 * ((g - b) / (max - min)) + 360;
    } else if (max === g) {
      h = 60 * ((b - r) / (max - min)) + 120;
    } else if (max === b) {
      h = 60 * ((r - g) / (max - min)) + 240;
    }

    const h255 = Math.floor(h / 2);
    const s255 = Math.round(s * 255);
    const v255 = Math.round(v * 255);
    return [h255, s255, v255];
  }

  document.addEventListener('DOMContentLoaded', init);
})();
