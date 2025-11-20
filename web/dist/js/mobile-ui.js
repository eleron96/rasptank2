(function () {
  const els = {
    video: document.getElementById('video-stream-mobile'),
    connectionIndicator: document.getElementById('connection-indicator-mobile'),
    connectionLabel: document.getElementById('connection-label-mobile'),
    batteryPercentHeader: document.getElementById('battery-percent-mobile'),
    batteryVoltageChip: document.getElementById('battery-voltage-mobile'),
    batteryPercentChip: document.getElementById('battery-percent-chip'),
    batteryPercentTelemetry: document.getElementById('battery-percent-telemetry'),
    cpuUsage: document.getElementById('cpu-usage-mobile'),
    cpuTemp: document.getElementById('cpu-temp-mobile'),
    ramUsage: document.getElementById('ram-usage-mobile'),
    distanceChip: document.getElementById('distance-chip-mobile'),
    distanceTelemetry: document.getElementById('distance-monitor-mobile'),
    distanceStatusLabel: document.getElementById('distance-status-label-mobile'),
    connectionQuality: document.getElementById('connection-quality-mobile'),
    gyro: {
      x: document.getElementById('gyro-x-mobile'),
      y: document.getElementById('gyro-y-mobile'),
      z: document.getElementById('gyro-z-mobile')
    },
    accel: {
      x: document.getElementById('accel-x-mobile'),
      y: document.getElementById('accel-y-mobile'),
      z: document.getElementById('accel-z-mobile')
    },
    modeTelemetry: document.getElementById('mode-telemetry-label-mobile'),
    speedSlider: document.getElementById('speed-slider-mobile'),
    speedLabel: document.getElementById('speed-value-mobile'),
    quickActions: Array.from(document.querySelectorAll('[data-action][data-off]')),
    armButtons: Array.from(document.querySelectorAll('[data-command][data-stop]')),
    modeActiveBtn: document.getElementById('mode-active-btn'),
    modeEcoBtn: document.getElementById('mode-eco-btn'),
    hdBtn: document.getElementById('mode-hd-btn'),
    joystick: {
      base: document.getElementById('joystick-base'),
      knob: document.getElementById('joystick-knob')
    }
  };

  const state = {
    ws: null,
    eventSource: null,
    reconnectTimer: null,
    infoTimer: null,
    connected: false,
    lastInfoTs: null,
    drive: { dir: null, turn: null },
    speed: parseInt(els.speedSlider?.value || '100', 10),
    batteryMeta: { min_voltage: 6.8, max_voltage: 8.4, scale: 8.4 },
    voltageEma: null,
    cameraHQ: false,
    systemMode: 'ACTIVE'
  };

  function setText (el, value) {
    if (!el) return;
    el.textContent = value;
  }

  function toggleClasses (el, mapping) {
    if (!el) return;
    Object.entries(mapping).forEach(([klass, enabled]) => {
      el.classList.toggle(klass, !!enabled);
    });
  }

  function parseNumber (value) {
    const num = Number(value);
    return Number.isFinite(num) ? num : null;
  }

  function voltageToPercent (voltage) {
    if (!Number.isFinite(voltage)) return null;
    const maxVoltage = Number(state.batteryMeta?.max_voltage ?? state.batteryMeta?.scale ?? 8.4);
    const minVoltage = Number(state.batteryMeta?.min_voltage ?? 6.8);
    const span = maxVoltage - minVoltage;
    if (span <= 0) return null;
    const pct = ((voltage - minVoltage) / span) * 100;
    return Math.max(0, Math.min(100, pct));
  }

  function smoothVoltage (value) {
    if (!Number.isFinite(value)) return state.voltageEma;
    const alpha = 0.35;
    state.voltageEma = state.voltageEma == null ? value : alpha * value + (1 - alpha) * state.voltageEma;
    return state.voltageEma;
  }

  function updateConnection (online) {
    state.connected = online;
    if (online) {
      setText(els.connectionIndicator, 'wifi');
      setText(els.connectionLabel, 'Online');
      toggleClasses(els.connectionIndicator, { 'text-emerald-600': true, 'text-slate-400': false });
      toggleClasses(els.connectionLabel, { 'text-emerald-700': true, 'text-slate-600': false });
    } else {
      setText(els.connectionIndicator, 'wifi_off');
      setText(els.connectionLabel, 'Offline');
      toggleClasses(els.connectionIndicator, { 'text-emerald-600': false, 'text-slate-400': true });
      toggleClasses(els.connectionLabel, { 'text-emerald-700': false, 'text-slate-600': true });
    }
    updateConnectionQuality();
  }

  function updateConnectionQuality () {
    const el = els.connectionQuality;
    if (!el) return;
    let label = '--';
    let classes = {
      'text-emerald-600': false,
      'text-amber-500': false,
      'text-rose-500': false,
      'text-slate-500': false
    };
    if (!state.connected) {
      label = 'Offline';
      classes['text-slate-500'] = true;
    } else if (!state.lastInfoTs) {
      label = 'Syncing';
      classes['text-amber-500'] = true;
    } else {
      const delta = (Date.now() - state.lastInfoTs) / 1000;
      if (delta < 1.8) {
        label = 'Excellent';
        classes['text-emerald-600'] = true;
      } else if (delta < 3.5) {
        label = 'Good';
        classes['text-amber-500'] = true;
      } else {
        label = 'Stale';
        classes['text-rose-500'] = true;
      }
    }
    setText(el, label);
    toggleClasses(el, classes);
  }

  function formatDistanceStatus (status) {
    const normalized = (status || '').toLowerCase();
    if (normalized === 'active') return 'Active';
    if (normalized === 'paused') return 'Paused';
    if (normalized === 'disabled') return 'Disabled';
    return 'Unknown';
  }

  function applyDistance (cm, status) {
    const numeric = parseNumber(cm);
    const value = Number.isFinite(numeric) ? `${numeric.toFixed(1)} cm` : '-- cm';
    setText(els.distanceChip, value);
    setText(els.distanceTelemetry, value);
    setText(els.distanceStatusLabel, formatDistanceStatus(status));
  }

  function applyBattery (voltage, percentage) {
    const smoothed = smoothVoltage(voltage);
    const percent = Number.isFinite(percentage) ? percentage : voltageToPercent(smoothed);
    setText(els.batteryVoltageChip, smoothed != null ? `${smoothed.toFixed(2)} V` : '-- V');
    if (percent != null) {
      const rounded = Math.round(percent);
      setText(els.batteryPercentHeader, rounded);
      setText(els.batteryPercentChip, `${rounded}%`);
      setText(els.batteryPercentTelemetry, rounded);
    } else {
      setText(els.batteryPercentHeader, '--');
      setText(els.batteryPercentChip, '--%');
      setText(els.batteryPercentTelemetry, '--');
    }
  }

  function applyMode (mode, fromServer = false) {
    const previous = state.systemMode;
    const upper = (mode || '').toUpperCase();
    if (upper) {
      state.systemMode = upper;
    }
    const effective = state.systemMode === 'STANDBY' ? 'ACTIVE' : state.systemMode;
    setText(els.modeTelemetry, effective === 'ECO' ? 'Eco' : 'Active');
    if (els.modeActiveBtn && els.modeEcoBtn) {
      const isEco = effective === 'ECO';
      toggleClasses(els.modeEcoBtn, {
        'bg-primary': isEco,
        'text-white': isEco,
        'bg-black/40': !isEco,
        'text-slate-300': !isEco
      });
      toggleClasses(els.modeActiveBtn, {
        'bg-primary': !isEco,
        'text-white': !isEco,
        'bg-black/40': isEco,
        'text-slate-300': isEco
      });
    }
    if (!fromServer && previous !== state.systemMode) {
      sendCommand(effective === 'ECO' ? 'modeEco' : 'modeActive');
    }
  }

  function applyHdState (enabled, fromServer = false) {
    const next = !!enabled;
    const previous = state.cameraHQ;
    state.cameraHQ = next;
    if (els.hdBtn) {
      toggleClasses(els.hdBtn, { 'text-primary': state.cameraHQ, 'text-slate-300': !state.cameraHQ });
    }
    if (!fromServer && previous !== state.cameraHQ) {
      sendCommand(state.cameraHQ ? 'cameraHQOn' : 'cameraHQOff');
      refreshVideoStream(true);
    }
  }

  function applyInfo (payload) {
    const data = payload.data || [];
    const battery = payload.battery || {};
    const distance = payload.distance || {};
    const gyro = payload.gyro || {};
    const accel = payload.accel || {};
    const camera = payload.camera || {};

    state.lastInfoTs = Date.now();

    const cpuTemp = parseNumber(data[0]);
    const cpuUse = parseNumber(data[1]);
    const ramUsage = parseNumber(data[2]);
    if (cpuTemp != null) setText(els.cpuTemp, `${cpuTemp.toFixed(1)}°C`);
    if (cpuUse != null) setText(els.cpuUsage, `${cpuUse.toFixed(0)}%`);
    if (ramUsage != null) setText(els.ramUsage, `${ramUsage.toFixed(0)}%`);

    const voltageCandidates = [
      typeof battery.voltage === 'number' ? battery.voltage : null,
      parseNumber(battery.voltage_display),
      parseNumber(data[3])
    ];
    const voltage = voltageCandidates.find((val) => Number.isFinite(val));
    const percentCandidates = [
      typeof battery.percentage === 'number' ? battery.percentage : null,
      parseNumber(battery.percentage_display),
      parseNumber(data[4])
    ];
    const percentage = percentCandidates.find((val) => Number.isFinite(val));
    applyBattery(voltage, percentage);

    setText(els.gyro.x, gyro.x ?? data[5] ?? '--');
    setText(els.gyro.y, gyro.y ?? data[6] ?? '--');
    setText(els.gyro.z, gyro.z ?? data[7] ?? '--');
    setText(els.accel.x, accel.x ?? data[8] ?? '--');
    setText(els.accel.y, accel.y ?? data[9] ?? '--');
    setText(els.accel.z, accel.z ?? data[10] ?? '--');

    applyDistance(distance.cm ?? distance.display, distance.status);

    if (camera && typeof camera === 'object') {
      if (camera.mode) {
        applyMode(camera.mode, true);
      }
      if (typeof camera.high_quality === 'boolean') {
        applyHdState(camera.high_quality, true);
      }
    } else if (payload.mode) {
      applyMode(payload.mode, true);
    }
    updateConnectionQuality();
  }

  function handleMessage (raw) {
    if (!raw) return;
    let payload = null;
    try {
      payload = JSON.parse(raw);
    } catch (err) {
      return;
    }
    if (payload?.title === 'get_info') {
      applyInfo(payload);
    }
  }

  function sendRaw (value) {
    if (!state.ws || state.ws.readyState !== WebSocket.OPEN) return;
    try {
      state.ws.send(value);
    } catch (err) {
      console.warn('Failed to send ws message', err);
    }
  }

  function sendCommand (command) {
    if (!command) return;
    sendRaw(command);
  }

  function scheduleReconnect () {
    if (state.reconnectTimer) return;
    state.reconnectTimer = window.setTimeout(() => {
      state.reconnectTimer = null;
      connectWebSocket();
    }, 1500);
  }

  function startInfoPolling () {
    if (state.infoTimer) {
      window.clearInterval(state.infoTimer);
    }
    state.infoTimer = window.setInterval(() => {
      sendCommand('get_info');
    }, 1000);
  }

  function connectWebSocket () {
    if (state.ws) {
      try { state.ws.close(); } catch (err) {}
    }
    const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(`${scheme}://${window.location.host}/ws`);
    state.ws = ws;

    ws.addEventListener('open', () => {
      updateConnection(true);
      sendRaw('admin:123456');
      sendCommand('get_info');
      startInfoPolling();
    });

    ws.addEventListener('message', (event) => {
      handleMessage(event.data);
    });

    ws.addEventListener('close', () => {
      updateConnection(false);
      state.lastInfoTs = null;
      updateConnectionQuality();
      scheduleReconnect();
    });

    ws.addEventListener('error', () => {
      try { ws.close(); } catch (err) {}
    });
  }

  function setupJoystick () {
    const base = els.joystick.base;
    const knob = els.joystick.knob;
    if (!base || !knob) return;
    const maxRadius = Math.min(base.clientWidth, base.clientHeight) / 2 - 10;
    let active = false;

    function updateDrive (nx, ny) {
      const threshold = 0.2;
      const dir = ny < -threshold ? 'forward' : ny > threshold ? 'backward' : null;
      const turn = nx < -threshold ? 'left' : nx > threshold ? 'right' : null;

      if (state.drive.dir !== dir) {
        if (dir) {
          sendCommand(dir);
        } else if (state.drive.dir) {
          sendCommand('DS');
        }
        state.drive.dir = dir;
      }
      if (state.drive.turn !== turn) {
        if (turn) {
          sendCommand(turn);
        } else if (state.drive.turn) {
          sendCommand('TS');
        }
        state.drive.turn = turn;
      }
    }

    function handlePointerDown (e) {
      active = true;
      base.setPointerCapture(e.pointerId);
      handlePointerMove(e);
    }

    function handlePointerMove (e) {
      if (!active) return;
      const rect = base.getBoundingClientRect();
      const cx = rect.left + rect.width / 2;
      const cy = rect.top + rect.height / 2;
      const dx = e.clientX - cx;
      const dy = e.clientY - cy;
      const distance = Math.min(Math.hypot(dx, dy), maxRadius);
      const angle = Math.atan2(dy, dx);
      const x = Math.cos(angle) * distance;
      const y = Math.sin(angle) * distance;

      knob.style.transform = `translate(calc(-50% + ${x}px), calc(-50% + ${y}px))`;
      const normX = +(x / maxRadius).toFixed(2);
      const normY = +(y / maxRadius).toFixed(2);
      updateDrive(normX, normY);
    }

    function resetJoystick (e) {
      active = false;
      try {
        if (e && e.pointerId && base.hasPointerCapture(e.pointerId)) {
          base.releasePointerCapture(e.pointerId);
        }
      } catch (err) {}
      knob.style.transform = 'translate(-50%, -50%)';
      state.drive.dir = null;
      state.drive.turn = null;
      sendCommand('DS');
      sendCommand('TS');
    }

    base.addEventListener('pointerdown', handlePointerDown);
    base.addEventListener('pointermove', handlePointerMove);
    base.addEventListener('pointerup', resetJoystick);
    base.addEventListener('pointercancel', resetJoystick);
    base.addEventListener('pointerleave', (e) => {
      if (!active) return;
      resetJoystick(e);
    });
  }

  function setupSpeed () {
    if (!els.speedSlider) return;
    const update = () => {
      const value = parseInt(els.speedSlider.value, 10);
      if (Number.isNaN(value)) return;
      state.speed = value;
      setText(els.speedLabel, value);
      window.clearTimeout(update.debounce);
      update.debounce = window.setTimeout(() => {
        sendCommand(`wsB ${state.speed}`);
      }, 180);
    };
    els.speedSlider.addEventListener('input', update);
    update();
  }

  function setupQuickActions () {
    els.quickActions.forEach((btn) => {
      btn.dataset.state = 'off';
      btn.addEventListener('click', () => {
        const isOn = btn.dataset.state !== 'on';
        btn.dataset.state = isOn ? 'on' : 'off';
        toggleClasses(btn, { 'ring-1': isOn, 'ring-primary/60': isOn });
        const command = isOn ? btn.dataset.action : btn.dataset.off;
        sendCommand(command);
      });
    });
  }

  function setupArmButtons () {
    els.armButtons.forEach((btn) => {
      const command = btn.dataset.command;
      const stop = btn.dataset.stop;
      if (!command) return;
      const press = (evt) => {
        evt.preventDefault();
        btn.classList.add('ring-1', 'ring-primary/50');
        sendCommand(command);
        const release = () => {
          btn.classList.remove('ring-1', 'ring-primary/50');
          if (stop) {
            sendCommand(stop);
          }
          document.removeEventListener('pointerup', release);
          document.removeEventListener('pointercancel', release);
          document.removeEventListener('pointerleave', release);
        };
        document.addEventListener('pointerup', release, { once: true });
        document.addEventListener('pointercancel', release, { once: true });
        document.addEventListener('pointerleave', release, { once: true });
      };
      btn.addEventListener('pointerdown', press);
    });
  }

  function setupModes () {
    els.modeActiveBtn?.addEventListener('click', () => applyMode('ACTIVE'));
    els.modeEcoBtn?.addEventListener('click', () => applyMode('ECO'));
    els.hdBtn?.addEventListener('click', () => applyHdState(!state.cameraHQ));
  }

  function refreshVideoStream (force = false) {
    if (!els.video) return;
    const suffix = `ts=${Date.now()}`;
    const connector = els.video.src.includes('?') ? '&' : '?';
    if (force || !els.video.src) {
      els.video.src = `/video_feed?${suffix}`;
    } else {
      els.video.src = `${els.video.src}${connector}${suffix}`;
    }
  }

  async function fetchCalibration () {
    try {
      const resp = await fetch('/api/calibration', { cache: 'no-store' });
      if (!resp.ok) return;
      const data = await resp.json();
      if (data?.calibration) {
        state.batteryMeta = {
          ...state.batteryMeta,
          ...data.calibration
        };
      }
      applyBattery(data?.voltage, data?.calibration ? undefined : null);
    } catch (err) {
      console.warn('Calibration fetch failed', err);
    }
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
          applyDistance(payload.cm ?? payload.display, payload.status);
        } catch (err) {
          console.warn('distance_update parse failed', err);
        }
      });
      source.addEventListener('battery_status', (event) => {
        try {
          const payload = JSON.parse(event.data || '{}');
          applyBattery(payload.voltage ?? payload.raw_voltage, payload.percentage);
        } catch (err) {
          console.warn('battery_status parse failed', err);
        }
      });
    } catch (err) {
      console.warn('SSE unavailable', err);
    }
  }

  function cleanup () {
    if (state.ws) {
      try { state.ws.close(); } catch (err) {}
    }
    if (state.eventSource) {
      try { state.eventSource.close(); } catch (err) {}
    }
    if (state.infoTimer) {
      window.clearInterval(state.infoTimer);
    }
    if (state.reconnectTimer) {
      window.clearTimeout(state.reconnectTimer);
    }
  }

  function init () {
    refreshVideoStream(true);
    setupJoystick();
    setupSpeed();
    setupQuickActions();
    setupArmButtons();
    setupModes();
    setupEvents();
    connectWebSocket();
    fetchCalibration();
    window.addEventListener('beforeunload', cleanup);
    window.addEventListener('pagehide', cleanup);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
