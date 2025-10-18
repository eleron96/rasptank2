(function () {
  'use strict';

  const controlState = { direction: 'stop', turn: 'stop' };
  let cachedStore = null;
  let pointerCoarseQuery = null;
  let responsiveListenersBound = false;

  const indicatorMap = {
    'forward|left': { label: 'Вперед + Влево', className: 'dir-forward-left' },
    'forward|right': { label: 'Вперед + Вправо', className: 'dir-forward-right' },
    'forward|stop': { label: 'Вперед', className: 'dir-forward' },
    'backward|left': { label: 'Назад + Влево', className: 'dir-backward-left' },
    'backward|right': { label: 'Назад + Вправо', className: 'dir-backward-right' },
    'backward|stop': { label: 'Назад', className: 'dir-backward' },
    'stop|left': { label: 'Поворот влево', className: 'dir-left' },
    'stop|right': { label: 'Поворот вправо', className: 'dir-right' },
    'stop|stop': { label: 'Стоп', className: 'dir-stop' }
  };

  function onReady(callback) {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', callback, { once: true });
    } else {
      callback();
    }
  }

  function ensureStore() {
    if (cachedStore && typeof cachedStore.dispatch === 'function') {
      return cachedStore;
    }

    const seen = new Set();
    const queue = [];

    function enqueue(instance) {
      if (instance && !seen.has(instance)) {
        seen.add(instance);
        queue.push(instance);
      }
    }

    const appRoot = document.getElementById('app');
    if (appRoot && appRoot.__vue__) {
      enqueue(appRoot.__vue__);
    }

    const dataApp = document.querySelector('[data-app="true"]');
    if (dataApp && dataApp.__vue__) {
      enqueue(dataApp.__vue__);
    }

    while (queue.length) {
      const instance = queue.shift();
      if (!instance) {
        continue;
      }
      if (instance.$store && typeof instance.$store.dispatch === 'function') {
        cachedStore = instance.$store;
        return cachedStore;
      }
      if (instance.$children && instance.$children.length) {
        instance.$children.forEach(enqueue);
      }
      if (instance.$parent) {
        enqueue(instance.$parent);
      }
      if (instance.$root) {
        enqueue(instance.$root);
      }
    }

    return null;
  }

  function collectVueInstances(predicate) {
    const results = [];
    const seen = new Set();
    const queue = [];

    function enqueue(instance) {
      if (!instance || seen.has(instance)) {
        return;
      }
      seen.add(instance);
      queue.push(instance);
    }

    const store = ensureStore();
    if (store && store._vm && store._vm.$root) {
      enqueue(store._vm.$root);
    }

    const appRoot = document.getElementById('app');
    if (appRoot && appRoot.__vue__) {
      enqueue(appRoot.__vue__);
    }

    const dataApp = document.querySelector('[data-app="true"]');
    if (dataApp && dataApp.__vue__) {
      enqueue(dataApp.__vue__);
    }

    while (queue.length) {
      const instance = queue.shift();
      if (!instance) {
        continue;
      }
      if (!predicate || predicate(instance)) {
        results.push(instance);
      }
      if (instance.$children && instance.$children.length) {
        for (let index = 0; index < instance.$children.length; index += 1) {
          enqueue(instance.$children[index]);
        }
      }
    }

    return results;
  }

  function toArray(value) {
    if (!value) {
      return [];
    }
    if (Array.isArray(value)) {
      return value;
    }
    return [value];
  }

  function buildButtonsDetail(source) {
    const blankTemplate = {
      isIcon: false,
      content: '',
      sendContent: undefined,
      sendKey: undefined,
      upSendContent: undefined,
      reversSendContent: undefined
    };
    return source.map(function (entry) {
      if (!entry || entry === '') {
        return Object.assign({}, blankTemplate);
      }
      const button = Object.assign({}, blankTemplate);
      const keys = Object.keys(button);
      for (let index = 0; index < keys.length; index += 1) {
        button[keys[index]] = entry[index];
      }
      return button;
    });
  }

  function applyChipVariants(vm) {
    if (!vm || typeof vm.$nextTick !== 'function') {
      return;
    }
    const variants = Array.isArray(vm.__chipVariants) ? vm.__chipVariants : [];
    vm.$nextTick(function () {
      const refs = toArray(vm.$refs && vm.$refs.chips);
      refs.forEach(function (chipRef, index) {
        if (!chipRef) {
          return;
        }
        const el = chipRef.$el || chipRef;
        if (!el || !el.setAttribute) {
          return;
        }
        const variant = variants[index] || null;
        if (variant) {
          el.setAttribute('data-variant', variant);
        } else {
          el.removeAttribute('data-variant');
        }
      });
    });
  }

  function ensureInstructionCollapsed() {
    const cards = document.querySelectorAll('.mod-sheet');
    cards.forEach(function (card) {
      if (!card || card.dataset.instructionToggleReady === 'true') {
        return;
      }
      const title = card.querySelector('.mod-title');
      if (!title || !title.textContent) {
        return;
      }
      const label = title.textContent.trim().toLowerCase();
      if (label !== 'instruction' && label !== 'инструкция') {
        return;
      }
      card.dataset.instructionToggleReady = 'true';
      card.classList.add('has-instruction-toggle');
      card.classList.add('is-instruction-collapsed');

      const toggle = document.createElement('button');
      toggle.type = 'button';
      toggle.className = 'instruction-toggle';
      toggle.setAttribute('aria-expanded', 'false');
      toggle.textContent = 'Показать';

      const updateState = function () {
        const collapsed = card.classList.contains('is-instruction-collapsed');
        toggle.textContent = collapsed ? 'Показать' : 'Скрыть';
        toggle.setAttribute('aria-expanded', String(!collapsed));
      };

      const toggleState = function () {
        card.classList.toggle('is-instruction-collapsed');
        updateState();
      };

      toggle.addEventListener('click', function (event) {
        event.stopPropagation();
        toggleState();
      });

      title.addEventListener('click', function (event) {
        if (event.target === toggle) {
          return;
        }
        toggleState();
      });

      title.appendChild(toggle);
      updateState();
    });
  }

  function enhanceMoveControlModules() {
    const instances = collectVueInstances(function (instance) {
      return instance && instance.$options && instance.$options.name === 'MoveControlMod';
    });
    instances.forEach(function (vm) {
      if (!vm || vm.__moveEnhanced) {
        return;
      }
      const original = Array.isArray(vm.buttons) ? vm.buttons : [];
      if (original.length !== 6) {
        vm.__moveEnhanced = true;
        return;
      }
      const reshaped = [
        '',
        [true, 'mdi-arrow-up-thick', 'forward', 87, 'DS'],
        '',
        [true, 'mdi-arrow-left-thick', 'left', 65, 'TS'],
        '',
        [true, 'mdi-arrow-right-thick', 'right', 68, 'TS'],
        '',
        [true, 'mdi-arrow-down-thick', 'backward', 83, 'DS'],
        ''
      ];
      vm.buttons = reshaped;
      vm.__moveEnhanced = true;
      if (typeof vm.$forceUpdate === 'function') {
        vm.$forceUpdate();
      }
      toArray(vm.$children).forEach(function (child) {
        if (!child || child.$options.name !== 'ButtonsChild') {
          return;
        }
        child.buttons = reshaped;
        child.buttonsDetail = buildButtonsDetail(reshaped);
        child.cols = 3;
        if (typeof child.$forceUpdate === 'function') {
          child.$forceUpdate();
        }
      });
    });
  }

  function enhanceActionsCards() {
    const cards = document.querySelectorAll('.mod-sheet');
    cards.forEach(function (card) {
      if (!card) {
        return;
      }
      const title = card.querySelector('.mod-title');
      if (!title || !title.textContent) {
        return;
      }
      const label = title.textContent.trim().toLowerCase();
      if (label === 'actions' || label === 'действия') {
        card.classList.add('actions-card');
      }
    });
  }

  let statusRetryTimer = null;
  let statusWatcherBound = false;
  let statusWatcherPending = false;
  let statusEnhancementReady = false;

  function enhanceStatusModules() {
    const instances = collectVueInstances(function (instance) {
      return instance && instance.$options && instance.$options.name === 'StatusMod';
    });
    let applied = false;
    let found = false;

    instances.forEach(function (vm) {
      if (!vm || vm.__gyroEnhanced) {
        if (vm) {
          found = true;
        }
        return;
      }

      found = true;
      const existing = Array.isArray(vm.chips) ? vm.chips.slice(0) : [];
      const getExistingValue = function (index) {
        if (index < existing.length && Array.isArray(existing[index]) && existing[index].length >= 3) {
          return existing[index][2];
        }
        return '--';
      };

      const newChips = [
        ['CPU', 'Temp', getExistingValue(0), '°C', 55, 70, 'cpu'],
        ['CPU', 'Usage', getExistingValue(1), '%', 70, 85, 'cpu'],
        ['RAM', 'Usage', getExistingValue(2), '%', 70, 85, 'cpu'],
        ['Battery', 'Voltage', '--', 'V', 7.0, 6.6, 'battery'],
        ['Battery', 'Charge', '--', '%', 50, 30, 'battery'],
        ['Gyro', 'X', '--', '°/s', 25, 75, 'imu'],
        ['Gyro', 'Y', '--', '°/s', 25, 75, 'imu'],
        ['Gyro', 'Z', '--', '°/s', 25, 75, 'imu'],
        ['Accel', 'X', '--', 'g', 0.3, 0.8, 'imu'],
        ['Accel', 'Y', '--', 'g', 0.3, 0.8, 'imu'],
        ['Accel', 'Z', '--', 'g', 0.3, 0.8, 'imu']
      ];

      if (typeof vm.$set === 'function') {
        vm.$set(vm, 'chips', newChips);
      } else {
        vm.chips = newChips;
      }
      vm.__chipVariants = newChips.map(function (chip) {
        return chip && chip.length >= 7 ? chip[6] : null;
      });

      const chipColorFn = function chipColorEnhanced() {
        const colors = [];
        for (let index = 0; index < this.chips.length; index += 1) {
          const chip = this.chips[index];
          if (!chip || chip.length < 6) {
            colors.push('grey darken-1');
            continue;
          }
          const rawValue = parseFloat(chip[2]);
          const safeThreshold = parseFloat(chip[4]);
          const warnThreshold = parseFloat(chip[5]);
          const variant = chip.length >= 7 ? chip[6] : null;
          if (!Number.isFinite(rawValue)) {
            colors.push('grey darken-1');
            continue;
          }
          if (variant === 'battery') {
            if (Number.isFinite(safeThreshold) && rawValue >= safeThreshold) {
              colors.push('green');
              continue;
            }
            if (Number.isFinite(warnThreshold) && rawValue >= warnThreshold) {
              colors.push('orange');
              continue;
            }
            colors.push('red');
            continue;
          }
          const magnitude = Math.abs(rawValue);
          if (Number.isFinite(safeThreshold) && magnitude < safeThreshold) {
            colors.push('green');
          } else if (Number.isFinite(warnThreshold) && magnitude < warnThreshold) {
            colors.push('orange');
          } else {
            colors.push('red');
          }
        }
        return colors;
      };

      vm.$options.computed = Object.assign({}, vm.$options.computed, { chipColor: chipColorFn });
      if (vm._computedWatchers && vm._computedWatchers.chipColor) {
        vm._computedWatchers.chipColor.getter = chipColorFn;
        vm._computedWatchers.chipColor.dirty = true;
        if (typeof vm._computedWatchers.chipColor.evaluate === 'function') {
          try {
            vm._computedWatchers.chipColor.evaluate();
          } catch (error) {
            /* ignore */
          }
        }
      }
      vm.__gyroEnhanced = true;
      applied = true;
      if (typeof vm.$forceUpdate === 'function') {
        vm.$forceUpdate();
      }
      applyChipVariants(vm);
    });

    if (applied || found) {
      statusEnhancementReady = true;
    }

    return applied;
  }

  function scheduleStatusRetry() {
    if (statusEnhancementReady || statusRetryTimer !== null || typeof window === 'undefined') {
      return;
    }
    statusRetryTimer = window.setTimeout(function () {
      statusRetryTimer = null;
      ensureStatusEnhancement();
    }, 400);
  }

  function ensureStatusEnhancement() {
    enhanceStatusModules();
    if (statusEnhancementReady) {
      const instances = collectVueInstances(function (instance) {
        return instance && instance.$options && instance.$options.name === 'StatusMod';
      });
      instances.forEach(applyChipVariants);
    }
    if (!statusEnhancementReady) {
      scheduleStatusRetry();
    }
  }

  function bindStatusWatcher() {
    if (statusWatcherBound) {
      return;
    }
    const store = ensureStore();
    if (!store || typeof store.watch !== 'function') {
      if (!statusWatcherPending && typeof window !== 'undefined') {
        statusWatcherPending = true;
        window.setTimeout(function () {
          statusWatcherPending = false;
          bindStatusWatcher();
        }, 500);
      }
      return;
    }
    statusWatcherBound = true;
    store.watch(
      function selectResponse(state) {
        return state && state.wsResponse;
      },
      function handleResponse() {
        ensureStatusEnhancement();
      }
    );
  }

  function dispatchCommand(command) {
    const store = ensureStore();
    if (!store) {
      return;
    }
    try {
      store.dispatch('changeWsContent', command);
    } catch (error) {
      console.warn('[rasptank-ui] cannot send command', error);
    }
  }

  function setDirection(next, options) {
    const force = options && options.force === true;
    const previous = controlState.direction;
    if (previous === next && !force) {
      return;
    }
    controlState.direction = next;
    if (next === 'stop') {
      if (previous !== 'stop' || force) {
        dispatchCommand('DS');
      }
    } else if (previous !== next || force) {
      dispatchCommand(next);
    }
  }

  function setTurn(next, options) {
    const force = options && options.force === true;
    const previous = controlState.turn;
    if (previous === next && !force) {
      return;
    }
    controlState.turn = next;
    if (next === 'stop') {
      if (previous !== 'stop' || force) {
        dispatchCommand('TS');
      }
    } else if (previous !== next || force) {
      dispatchCommand(next);
    }
  }

  function updateIndicator(indicator) {
    if (!indicator) {
      return;
    }
    const label = indicator.querySelector('.direction-label');
    const arrow = indicator.querySelector('.direction-arrow');
    if (!label || !arrow) {
      return;
    }

    const key = controlState.direction + '|' + controlState.turn;
    const config = indicatorMap[key] || indicatorMap['stop|stop'];

    label.textContent = config.label;
    label.classList.toggle('is-active', key !== 'stop|stop');
    arrow.className = 'direction-arrow ' + config.className;
  }

  function applyVector(indicator, touchZone, dx, dy, radius) {
    const distance = Math.hypot(dx, dy);
    const clampRadius = radius * 0.85;
    const effectiveDistance = Math.min(distance, clampRadius);
    const angle = distance > 0 ? Math.atan2(dy, dx) : 0;
    const clampedX = Math.cos(angle) * effectiveDistance;
    const clampedY = Math.sin(angle) * effectiveDistance;

    touchZone.style.setProperty('--joy-x', clampedX.toFixed(2) + 'px');
    touchZone.style.setProperty('--joy-y', clampedY.toFixed(2) + 'px');

    const deadZone = radius * 0.28;
    let direction = 'stop';
    let turn = 'stop';

    if (distance > deadZone) {
      if (dy <= -deadZone) {
        direction = 'forward';
      } else if (dy >= deadZone) {
        direction = 'backward';
      }

      if (dx <= -deadZone) {
        turn = 'left';
      } else if (dx >= deadZone) {
        turn = 'right';
      }
    }

    setDirection(direction);
    setTurn(turn);
    updateIndicator(indicator);
  }

  function getPointerQuery() {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      return null;
    }
    if (!pointerCoarseQuery) {
      try {
        pointerCoarseQuery = window.matchMedia('(pointer: coarse)');
      } catch (error) {
        pointerCoarseQuery = null;
      }
    }
    return pointerCoarseQuery;
  }

  function shouldEnableJoystick() {
    const query = getPointerQuery();
    if (query && query.matches) {
      return true;
    }
    const hasTouch = typeof navigator !== 'undefined' &&
      typeof navigator.maxTouchPoints === 'number' &&
      navigator.maxTouchPoints > 0;
    if (hasTouch && typeof window !== 'undefined' && typeof window.innerWidth === 'number') {
      return window.innerWidth <= 1100;
    }
    return false;
  }

  function bindResponsiveListeners() {
    if (responsiveListenersBound) {
      return;
    }
    responsiveListenersBound = true;

    const query = getPointerQuery();
    if (query) {
      const handler = function () {
        installEnhancements();
      };
      if (typeof query.addEventListener === 'function') {
        query.addEventListener('change', handler);
      } else if (typeof query.addListener === 'function') {
        query.addListener(handler);
      }
    }

    if (typeof window !== 'undefined') {
      window.addEventListener('resize', installEnhancements);
      window.addEventListener('orientationchange', installEnhancements);
    }
  }

  function buildJoystick(moduleRoot) {
    if (!moduleRoot || moduleRoot.dataset.joystickMounted === 'true') {
      return;
    }

    moduleRoot.dataset.joystickMounted = 'true';
    moduleRoot.classList.add('move-control-module');

    const legacyButtons = moduleRoot.querySelector('.button-child');
    if (legacyButtons) {
      legacyButtons.classList.add('legacy-drive-grid');
    }

    const panel = document.createElement('div');
    panel.className = 'joystick-panel';
    panel.innerHTML = [
      '<div class="joystick-direction">',
      '  <span class="direction-title">Направление</span>',
      '  <div class="direction-arrow dir-stop" aria-hidden="true">',
      '    <svg viewBox="0 0 24 24" fill="currentColor" focusable="false">',
      '      <path d="M12 3l7 7h-4v7h-6v-7H5z"></path>',
      '    </svg>',
      '  </div>',
      '  <span class="direction-label">Стоп</span>',
      '</div>',
      '<div class="joystick-touch" role="application" aria-label="Виртуальный джойстик управления движением">',
      '  <div class="joystick-base"></div>',
      '  <div class="joystick-thumb"></div>',
      '</div>'
    ].join('');

    const sliderInput = moduleRoot.querySelector('.v-input');
    if (sliderInput && sliderInput.parentElement === moduleRoot) {
      moduleRoot.insertBefore(panel, sliderInput);
    } else if (sliderInput && sliderInput.parentElement) {
      sliderInput.parentElement.insertBefore(panel, sliderInput);
    } else {
      moduleRoot.insertBefore(panel, moduleRoot.firstChild);
    }

    const indicator = panel.querySelector('.joystick-direction');
    const touchZone = panel.querySelector('.joystick-touch');
    if (!indicator || !touchZone) {
      return;
    }

    updateIndicator(indicator);

    let activePointer = null;
    let activeTouchId = null;

    const centerThumb = function () {
      touchZone.style.setProperty('--joy-x', '0px');
      touchZone.style.setProperty('--joy-y', '0px');
    };

    const resetStick = function () {
      if (activePointer !== null && typeof touchZone.releasePointerCapture === 'function') {
        try {
          touchZone.releasePointerCapture(activePointer);
        } catch (error) {
          /* ignore */
        }
      }
      activePointer = null;
      activeTouchId = null;
      centerThumb();
      touchZone.classList.remove('is-active');
      updateIndicator(indicator);
      setDirection('stop', { force: true });
      setTurn('stop', { force: true });
    };

    const handleVector = function (clientX, clientY) {
      const rect = touchZone.getBoundingClientRect();
      const radius = rect.width / 2;
      const centerX = rect.left + radius;
      const centerY = rect.top + radius;
      const dx = clientX - centerX;
      const dy = clientY - centerY;

      applyVector(indicator, touchZone, dx, dy, radius);
      touchZone.classList.add('is-active');
    };

    if (typeof window !== 'undefined' && 'PointerEvent' in window) {
      touchZone.addEventListener('pointerdown', function (event) {
        if (activePointer !== null && activePointer !== event.pointerId) {
          return;
        }
        activePointer = event.pointerId;
        if (typeof touchZone.setPointerCapture === 'function') {
          try {
            touchZone.setPointerCapture(event.pointerId);
          } catch (error) {
            /* ignore */
          }
        }
        event.preventDefault();
        handleVector(event.clientX, event.clientY);
      }, { passive: false });

      touchZone.addEventListener('pointermove', function (event) {
        if (activePointer === null || event.pointerId !== activePointer) {
          return;
        }
        event.preventDefault();
        handleVector(event.clientX, event.clientY);
      }, { passive: false });

      const endPointer = function (event) {
        if (event && event.pointerId !== undefined && activePointer !== null && event.pointerId !== activePointer) {
          return;
        }
        resetStick();
      };

      touchZone.addEventListener('pointerup', endPointer, { passive: true });
      touchZone.addEventListener('pointercancel', endPointer, { passive: true });
      touchZone.addEventListener('pointerleave', endPointer, { passive: true });
      touchZone.addEventListener('lostpointercapture', endPointer);

      window.addEventListener('blur', resetStick);
      document.addEventListener('pointerup', endPointer, { passive: true });
      document.addEventListener('pointercancel', endPointer, { passive: true });
    } else {
      touchZone.addEventListener('touchstart', function (event) {
        if (activeTouchId !== null) {
          return;
        }
        const touch = event.changedTouches && event.changedTouches[0];
        if (!touch) {
          return;
        }
        activeTouchId = touch.identifier;
        event.preventDefault();
        handleVector(touch.clientX, touch.clientY);
      }, { passive: false });

      touchZone.addEventListener('touchmove', function (event) {
        if (activeTouchId === null) {
          return;
        }
        let touch = null;
        if (event.changedTouches && event.changedTouches.length) {
          for (let index = 0; index < event.changedTouches.length; index += 1) {
            if (event.changedTouches[index].identifier === activeTouchId) {
              touch = event.changedTouches[index];
              break;
            }
          }
        }
        if (!touch && event.touches && event.touches.length) {
          for (let index = 0; index < event.touches.length; index += 1) {
            if (event.touches[index].identifier === activeTouchId) {
              touch = event.touches[index];
              break;
            }
          }
        }
        if (!touch) {
          return;
        }
        event.preventDefault();
        handleVector(touch.clientX, touch.clientY);
      }, { passive: false });

      const endTouch = function (event) {
        if (activeTouchId === null) {
          resetStick();
          return;
        }
        if (!event.changedTouches || !event.changedTouches.length) {
          resetStick();
          return;
        }
        for (let index = 0; index < event.changedTouches.length; index += 1) {
          if (event.changedTouches[index].identifier === activeTouchId) {
            resetStick();
            return;
          }
        }
      };

      touchZone.addEventListener('touchend', endTouch);
      touchZone.addEventListener('touchcancel', endTouch);
      window.addEventListener('blur', resetStick);
    }
  }

  function findMoveModule() {
    const titles = document.querySelectorAll('.mod-sheet .mod-title');
    for (let index = 0; index < titles.length; index += 1) {
      const title = titles[index];
      if (!title || !title.textContent) {
        continue;
      }
      if (title.textContent.trim().toLowerCase() !== 'move control') {
        continue;
      }
      const sheet = title.closest('.mod-sheet');
      if (!sheet) {
        continue;
      }
      const wrapper = sheet.querySelector('.mod-wrapper');
      if (!wrapper) {
        continue;
      }
      const moduleRoot = wrapper.firstElementChild || wrapper;
      return { sheet: sheet, moduleRoot: moduleRoot };
    }
    return null;
  }

  function removeAboutUs() {
    const headers = document.querySelectorAll('.v-expansion-panel-header');
    headers.forEach(function (header) {
      if (!header || !header.textContent) {
        return;
      }
      if (header.textContent.trim().toLowerCase() !== 'about us') {
        return;
      }
      const panel = header.closest('.v-expansion-panel');
      if (panel && !panel.hasAttribute('data-about-removed')) {
        panel.setAttribute('data-about-removed', 'true');
        panel.remove();
      }
    });
  }

  function installEnhancements() {
    removeAboutUs();
    ensureStatusEnhancement();
    ensureInstructionCollapsed();
    enhanceActionsCards();
    enhanceMoveControlModules();
    const target = findMoveModule();
    if (!target) {
      return;
    }

    const wantJoystick = shouldEnableJoystick();
    let panel = target.moduleRoot.querySelector('.joystick-panel');

    if (wantJoystick) {
      if (!panel) {
        buildJoystick(target.moduleRoot);
        panel = target.moduleRoot.querySelector('.joystick-panel');
      }
      if (panel) {
        panel.hidden = false;
        panel.classList.remove('is-hidden');
      }
      return;
    }

    if (panel) {
      panel.hidden = true;
      panel.classList.add('is-hidden');
      setDirection('stop', { force: true });
      setTurn('stop', { force: true });
    }
  }

  onReady(function () {
    bindResponsiveListeners();
    installEnhancements();
    bindStatusWatcher();
    ensureStatusEnhancement();
    const observer = new MutationObserver(installEnhancements);
    observer.observe(document.body, { childList: true, subtree: true });
  });
})();
