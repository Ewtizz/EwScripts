/* NetPulse — клиент дашборда: SSE-поток измерений + отрисовка графиков на canvas. */
(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);

  // ------------------------------------------------------------ состояние

  const state = {
    history: [],        // последние точки измерений
    range: 60,          // окно графика, с
    paused: false,      // заморозка отображения (сбор данных и лог продолжаются)
    bits: false,        // показывать биты/с вместо байт/с
    last: null,         // последний payload от сервера
    scale: 0,           // текущий (анимированный) масштаб оси Y, байт/с
    hover: null,        // позиция курсора над графиком
    connected: false,
  };

  // часовое окно при интервале 0,5 с — это 7200 точек, столько и держим
  const MAX_POINTS = 7200;
  const MIN_SCALE = 8 * 1024; // чтобы простаивающий график не рисовал шум во весь экран

  // ----------------------------------------------------------- форматтеры

  const nf = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 });
  const nf0 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 });

  const BYTE_UNITS = ['Б', 'КБ', 'МБ', 'ГБ', 'ТБ'];
  const BIT_UNITS = ['бит', 'Кбит', 'Мбит', 'Гбит', 'Тбит'];

  function scaleUnit(value, units, base) {
    let i = 0;
    while (Math.abs(value) >= base && i < units.length - 1) {
      value /= base;
      i++;
    }
    return { value, unit: units[i] };
  }

  const fmtBytes = (v) => {
    const { value, unit } = scaleUnit(v || 0, BYTE_UNITS, 1024);
    return `${unit === 'Б' ? nf0.format(value) : nf.format(value)} ${unit}`;
  };

  /** Скорость в выбранных единицах: {num, unit} — число и подпись отдельно. */
  function fmtRate(bytesPerSec) {
    if (state.bits) {
      const { value, unit } = scaleUnit((bytesPerSec || 0) * 8, BIT_UNITS, 1000);
      return { num: unit === 'бит' ? nf0.format(value) : nf.format(value), unit: `${unit}/с` };
    }
    const { value, unit } = scaleUnit(bytesPerSec || 0, BYTE_UNITS, 1024);
    return { num: unit === 'Б' ? nf0.format(value) : nf.format(value), unit: `${unit}/с` };
  }

  const rateText = (v) => { const r = fmtRate(v); return `${r.num} ${r.unit}`; };

  const fmtBits = (bytesPerSec) => {
    const { value, unit } = scaleUnit((bytesPerSec || 0) * 8, BIT_UNITS, 1000);
    return `${unit === 'бит' ? nf0.format(value) : nf.format(value)} ${unit}/с`;
  };

  function fmtDuration(seconds) {
    const s = Math.max(0, Math.floor(seconds || 0));
    const pad = (n) => String(n).padStart(2, '0');
    return `${pad(Math.floor(s / 3600))}:${pad(Math.floor((s % 3600) / 60))}:${pad(s % 60)}`;
  }

  const fmtClock = (epoch) =>
    new Date(epoch * 1000).toLocaleTimeString('ru-RU', { hour12: false });

  const css = (name) =>
    getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  // -------------------------------------------------------------- canvas

  /** Подгоняет размер буфера canvas под CSS-размер и плотность экрана. */
  function fitCanvas(canvas) {
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    const w = Math.max(1, Math.round(rect.width * dpr));
    const h = Math.max(1, Math.round(rect.height * dpr));
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
    }
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { ctx, width: rect.width, height: rect.height };
  }

  /** Ближайшее «красивое» число сверху в двоичной шкале: 1/2/4/…/512 × 1024^k.
   *  Так и сама подпись, и её половина получаются круглыми: 2 МБ/с и 1 МБ/с. */
  const NICE_STEPS = [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024];

  function niceCeil(value) {
    if (value <= 0) return MIN_SCALE;
    const k = Math.max(0, Math.floor(Math.log(value) / Math.log(1024)));
    const base = Math.pow(1024, k);
    const norm = value / base;
    return (NICE_STEPS.find((step) => step >= norm) ?? 1024) * base;
  }

  // ------------------------------------------------------- главный график

  const chart = $('chart');
  const tooltip = $('tooltip');

  function visiblePoints() {
    if (!state.history.length) return [];
    const now = state.history[state.history.length - 1].t;
    const from = now - state.range;
    // история отсортирована по времени — достаточно найти границу с конца
    let start = state.history.length;
    while (start > 0 && state.history[start - 1].t >= from) start--;
    return state.history.slice(start);
  }

  function drawChart() {
    const { ctx, width, height } = fitCanvas(chart);
    ctx.clearRect(0, 0, width, height);

    const points = visiblePoints();

    // масштаб: быстро растём под всплеск, медленно опускаемся — так график не дёргается
    let peak = 0;
    for (const p of points) peak = Math.max(peak, p.rx_bps, p.tx_bps);
    const target = Math.max(MIN_SCALE, niceCeil(peak * 1.15));
    if (!state.scale) state.scale = target;
    state.scale += (target - state.scale) * (target > state.scale ? 0.28 : 0.04);
    const scale = state.scale;

    // правое поле — по фактической ширине подписей: в битах они заметно длиннее
    ctx.font = '11px ' + css('--mono');
    const padL = 6, padT = 12, padB = 22;
    const padR = Math.ceil(
      Math.max(ctx.measureText(rateText(scale)).width,
               ctx.measureText(rateText(scale / 2)).width)) + 16;
    const plotW = Math.max(10, width - padL - padR);
    const plotH = Math.max(10, height - padT - padB);
    const mid = padT + plotH / 2;
    const half = plotH / 2;

    const now = points.length ? points[points.length - 1].t : Date.now() / 1000;
    const x = (t) => padL + plotW * (1 - (now - t) / state.range);
    const y = (bps, up) => (up ? mid - (bps / scale) * half : mid + (bps / scale) * half);

    // ---- сетка и подписи оси Y
    ctx.textBaseline = 'middle';
    ctx.textAlign = 'left';
    const gridColor = css('--grid');
    const mutedColor = css('--muted');

    for (const frac of [1, 0.5, 0]) {
      for (const up of frac === 0 ? [true] : [true, false]) {
        const yy = up ? mid - half * frac : mid + half * frac;
        ctx.beginPath();
        ctx.strokeStyle = frac === 0 ? css('--border-strong') : gridColor;
        ctx.lineWidth = 1;
        ctx.moveTo(padL, Math.round(yy) + 0.5);
        ctx.lineTo(padL + plotW, Math.round(yy) + 0.5);
        ctx.stroke();
        ctx.fillStyle = mutedColor;
        ctx.fillText(frac === 0 ? '0' : rateText(scale * frac), padL + plotW + 8, yy);
      }
    }

    // ---- подписи времени
    ctx.textAlign = 'center';
    const ticks = 5;
    for (let i = 0; i <= ticks; i++) {
      const t = now - state.range * (1 - i / ticks);
      const xx = padL + (plotW * i) / ticks;
      if (i > 0 && i < ticks) {
        ctx.beginPath();
        ctx.strokeStyle = gridColor;
        ctx.moveTo(Math.round(xx) + 0.5, padT);
        ctx.lineTo(Math.round(xx) + 0.5, padT + plotH);
        ctx.stroke();
      }
      // крайние подписи прижимаем к краям, иначе их срезает граница canvas
      ctx.textAlign = i === 0 ? 'left' : i === ticks ? 'right' : 'center';
      ctx.fillStyle = mutedColor;
      ctx.fillText(fmtClock(t), xx, height - padB / 2 + 2);
    }

    if (points.length < 2) {
      ctx.fillStyle = mutedColor;
      ctx.font = '13px ' + css('--font');
      ctx.fillText('Ожидание данных…', padL + plotW / 2, mid);
      return;
    }

    // ---- области приёма (вверх) и передачи (вниз)
    const series = [
      { key: 'rx_bps', up: true, color: css('--rx') },
      { key: 'tx_bps', up: false, color: css('--tx') },
    ];

    for (const s of series) {
      ctx.beginPath();
      ctx.moveTo(x(points[0].t), mid);
      for (const p of points) ctx.lineTo(x(p.t), y(p[s.key], s.up));
      ctx.lineTo(x(points[points.length - 1].t), mid);
      ctx.closePath();

      // у нулевой линии заливка плотная, к краю графика растворяется
      const grad = ctx.createLinearGradient(0, s.up ? mid - half : mid, 0, s.up ? mid : mid + half);
      grad.addColorStop(s.up ? 0 : 1, s.color + '0d');
      grad.addColorStop(s.up ? 1 : 0, s.color + '66');
      ctx.fillStyle = grad;
      ctx.fill();

      ctx.beginPath();
      points.forEach((p, i) => {
        const xx = x(p.t), yy = y(p[s.key], s.up);
        i === 0 ? ctx.moveTo(xx, yy) : ctx.lineTo(xx, yy);
      });
      ctx.strokeStyle = s.color;
      ctx.lineWidth = 1.8;
      ctx.lineJoin = 'round';
      ctx.stroke();

      // точка текущего значения
      const last = points[points.length - 1];
      ctx.beginPath();
      ctx.arc(x(last.t), y(last[s.key], s.up), 3.2, 0, Math.PI * 2);
      ctx.fillStyle = s.color;
      ctx.fill();
    }

    // ---- курсор и всплывающая подсказка
    if (state.hover && state.hover.x >= padL && state.hover.x <= padL + plotW) {
      let nearest = points[0], best = Infinity;
      for (const p of points) {
        const d = Math.abs(x(p.t) - state.hover.x);
        if (d < best) { best = d; nearest = p; }
      }
      const hx = x(nearest.t);
      ctx.beginPath();
      ctx.setLineDash([3, 3]);
      ctx.strokeStyle = css('--border-strong');
      ctx.moveTo(Math.round(hx) + 0.5, padT);
      ctx.lineTo(Math.round(hx) + 0.5, padT + plotH);
      ctx.stroke();
      ctx.setLineDash([]);

      for (const s of series) {
        ctx.beginPath();
        ctx.arc(hx, y(nearest[s.key], s.up), 3.5, 0, Math.PI * 2);
        ctx.fillStyle = s.color;
        ctx.fill();
      }

      tooltip.hidden = false;
      tooltip.innerHTML =
        `<div class="tooltip__time">${fmtClock(nearest.t)}</div>` +
        `<div class="tooltip__row"><span>↓ приём</span><b>${rateText(nearest.rx_bps)}</b></div>` +
        `<div class="tooltip__row"><span>↑ передача</span><b>${rateText(nearest.tx_bps)}</b></div>` +
        `<div class="tooltip__row"><span>пакетов</span><b>${nearest.rx_packets} / ${nearest.tx_packets}</b></div>`;
      const wrapW = chart.parentElement.clientWidth;
      const left = Math.min(Math.max(hx + 10, 90), wrapW - 90);
      tooltip.style.left = `${left}px`;
      tooltip.style.top = `${Math.max(70, state.hover.y - 12)}px`;
    } else {
      tooltip.hidden = true;
    }
  }

  // ------------------------------------------------------------ спарклайны

  function drawSpark(canvas, key, color) {
    const { ctx, width, height } = fitCanvas(canvas);
    ctx.clearRect(0, 0, width, height);
    const points = state.history.slice(-90);
    if (points.length < 2) return;

    let peak = 0;
    for (const p of points) peak = Math.max(peak, p[key]);
    peak = Math.max(peak, 1024);

    const x = (i) => (width * i) / (points.length - 1);
    const y = (v) => height - 3 - (v / peak) * (height - 8);

    ctx.beginPath();
    ctx.moveTo(0, height);
    points.forEach((p, i) => ctx.lineTo(x(i), y(p[key])));
    ctx.lineTo(width, height);
    ctx.closePath();
    const grad = ctx.createLinearGradient(0, 0, 0, height);
    grad.addColorStop(0, color + '3d');
    grad.addColorStop(1, color + '00');
    ctx.fillStyle = grad;
    ctx.fill();

    ctx.beginPath();
    points.forEach((p, i) => (i ? ctx.lineTo(x(i), y(p[key])) : ctx.moveTo(x(i), y(p[key]))));
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.stroke();
  }

  // -------------------------------------------------------- обновление UI

  function signalClass(percent) {
    if (percent >= 60) return '';
    if (percent >= 30) return 'weak';
    return 'bad';
  }

  function renderTiles(payload) {
    const sample = payload.sample || { rx_bps: 0, tx_bps: 0 };
    const session = payload.session || {};
    const wifi = payload.wifi || {};

    const rx = fmtRate(sample.rx_bps);
    const tx = fmtRate(sample.tx_bps);
    $('rxRate').textContent = rx.num;
    $('rxUnit').textContent = rx.unit;
    $('txRate').textContent = tx.num;
    $('txUnit').textContent = tx.unit;
    $('rxBits').textContent = state.bits ? fmtBytes(sample.rx_bps) + '/с' : fmtBits(sample.rx_bps);
    $('txBits').textContent = state.bits ? fmtBytes(sample.tx_bps) + '/с' : fmtBits(sample.tx_bps);
    $('rxTotal').textContent = fmtBytes(session.rx);
    $('txTotal').textContent = fmtBytes(session.tx);
    $('rxPeak').textContent = 'пик ' + rateText(session.peak_rx);
    $('txPeak').textContent = 'пик ' + rateText(session.peak_tx);

    // Wi-Fi
    const hasWifi = Boolean(wifi.ssid);
    $('ssid').textContent = hasWifi ? wifi.ssid : (payload.adapter?.is_wifi ? 'нет сети' : 'проводное подключение');
    $('wifiState').textContent = wifi.state || (payload.adapter?.status === 'up' ? 'активен' : '—');
    const percent = wifi.signal || 0;
    $('signalPct').textContent = hasWifi ? percent : '—';
    $('rssi').textContent = wifi.rssi != null ? `${wifi.rssi} dBm` : '— dBm';
    const bars = $('signalBars');
    bars.className = 'bars ' + signalClass(percent);
    [...bars.children].forEach((bar, i) => bar.classList.toggle('on', percent >= (i + 1) * 20));
    $('wifiMeta').textContent = hasWifi
      ? `канал ${wifi.channel || '—'} · ${wifi.band || '—'} · ${wifi.phy || '—'} · ${wifi.security || '—'}`
      : `${payload.adapter?.name || '—'}`;
  }

  function renderStats(payload) {
    const session = payload.session || {};
    const adapter = payload.adapter || {};
    $('sRx').textContent = fmtBytes(session.rx);
    $('sTx').textContent = fmtBytes(session.tx);
    $('sTotal').textContent = fmtBytes((session.rx || 0) + (session.tx || 0));
    $('sUptime').textContent = fmtDuration(session.uptime);
    $('sAvgRx').textContent = rateText(session.avg_rx);
    $('sAvgTx').textContent = rateText(session.avg_tx);
    $('sPackets').textContent =
      `${nf0.format(session.rx_packets || 0)} / ${nf0.format(session.tx_packets || 0)}`;
    $('sErrors').textContent =
      `${(adapter.rx_errors || 0) + (adapter.tx_errors || 0)} / ` +
      `${(adapter.rx_discards || 0) + (adapter.tx_discards || 0)}`;
  }

  function renderDetails(payload) {
    const a = payload.adapter || {};
    const w = payload.wifi || {};
    const mbps = (bps) => (bps ? `${nf.format(bps / 1e6)} Мбит/с` : '—');
    const rows = [
      ['Адаптер', a.name],
      ['Устройство', a.description],
      ['MAC-адрес', a.mac],
      ['IPv4', (a.ipv4 || []).join(', ')],
      ['Состояние', a.status === 'up' ? 'активен' : a.status],
      ['Скорость линка ↓', mbps(a.rx_link_bps)],
      ['Скорость линка ↑', mbps(a.tx_link_bps)],
      ['MTU', a.mtu ? `${a.mtu} байт` : ''],
      ['Сеть (SSID)', w.ssid],
      ['Точка доступа', w.bssid],
      ['Канал / диапазон', w.channel ? `${w.channel} · ${w.band || '—'}` : ''],
      ['Стандарт', w.phy],
      ['Защита', w.security ? `${w.security} · ${w.cipher || '—'}` : ''],
      ['Принято адаптером', a.rx_bytes_total != null ? fmtBytes(a.rx_bytes_total) : ''],
      ['Отправлено адаптером', a.tx_bytes_total != null ? fmtBytes(a.tx_bytes_total) : ''],
    ].filter(([, value]) => value !== undefined && value !== null && value !== '');

    $('details').innerHTML = rows
      .map(([label, value]) => `<div><dt>${label}</dt><dd>${escapeHtml(String(value))}</dd></div>`)
      .join('');
  }

  function escapeHtml(text) {
    return text.replace(/[&<>"']/g, (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function renderFooter(payload) {
    const interval = payload.interval || 1;
    const session = payload.session || {};
    $('footerLeft').textContent =
      `опрос каждые ${nf.format(interval)} с · точек в памяти: ${session.samples || 0}`;
    $('footerRight').textContent = state.connected
      ? `последнее обновление ${fmtClock(payload.sample ? payload.sample.t : Date.now() / 1000)}`
      : 'соединение с сервером потеряно';
  }

  function setStatus(kind, text) {
    const pill = $('statusPill');
    pill.className = 'pill pill--' + kind;
    $('statusText').textContent = text;
  }

  function apply(payload) {
    state.last = payload;
    renderTiles(payload);
    renderStats(payload);
    renderDetails(payload);
    renderFooter(payload);
  }

  // ----------------------------------------------------------- соединения

  async function loadConnections() {
    try {
      const res = await fetch('/api/connections');
      const data = await res.json();
      const box = $('connections');
      const list = data.connections || [];
      if (!list.length) {
        box.innerHTML = '<p class="empty">Нет активных внешних соединений</p>';
        $('connHint').textContent = 'по процессам';
        return;
      }
      $('connHint').textContent =
        `${list.reduce((sum, item) => sum + item.count, 0)} соединений`;
      box.innerHTML = list
        .map((item) => {
          const peers = item.peers
            .map((p) => {
              const host = p.host ? ` ${escapeHtml(p.host)}` : '';
              return `<span>→ ${escapeHtml(p.ip)}:${p.ports.join(',')}${host}</span>`;
            })
            .join('');
          return (
            `<div class="conn-row">` +
            `<div class="conn-row__name">${escapeHtml(item.process)}` +
            `<span class="conn-row__pid">PID ${item.pid}</span></div>` +
            `<div class="conn-row__count">${item.count}</div>` +
            `<div class="conn-row__peers">${peers}</div>` +
            `</div>`
          );
        })
        .join('');
    } catch {
      /* сервер мог уйти на перезапуск — просто ждём следующей попытки */
    }
  }

  // ------------------------------------------------------------- загрузка

  async function loadState() {
    const res = await fetch('/api/state');
    const data = await res.json();

    state.history = data.history || [];
    const select = $('adapterSelect');
    select.innerHTML = (data.adapters || [])
      .map((a) => {
        const mark = a.is_wifi ? '📶' : '🔌';
        const status = a.status === 'up' ? '' : ' (не активен)';
        return `<option value="${a.luid}"${a.selected ? ' selected' : ''}>` +
               `${mark} ${escapeHtml(a.name)}${status}</option>`;
      })
      .join('');
    $('intervalSelect').value = String(data.interval || 1);
    apply(data);
  }

  function connect() {
    const source = new EventSource('/api/stream');

    source.onopen = () => {
      state.connected = true;
      if (!state.paused) setStatus('live', 'в эфире');
    };

    source.onmessage = (event) => {
      const payload = JSON.parse(event.data);
      if (payload.type !== 'sample') return;
      if (state.paused) return;
      state.history.push(payload.sample);
      if (state.history.length > MAX_POINTS) state.history.shift();
      apply(payload);
    };

    source.onerror = () => {
      state.connected = false;
      setStatus('down', 'нет связи');
      // EventSource переподключается сам, отдельная логика не нужна
    };
  }

  // ------------------------------------------------------------ управление

  function bindControls() {
    $('adapterSelect').addEventListener('change', async (event) => {
      await fetch('/api/select', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ luid: Number(event.target.value) }),
      });
      state.history = [];
      state.scale = 0;
      await loadState();
    });

    $('intervalSelect').addEventListener('change', async (event) => {
      await fetch('/api/interval', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ interval: Number(event.target.value) }),
      });
    });

    $('resetBtn').addEventListener('click', async () => {
      await fetch('/api/reset', { method: 'POST' });
      state.history = [];
      state.scale = 0;
      await loadState();
    });

    const togglePause = () => {
      state.paused = !state.paused;
      $('pauseBtn').textContent = state.paused ? 'Продолжить' : 'Пауза';
      $('pauseBtn').classList.toggle('is-active', state.paused);
      if (state.paused) {
        setStatus('paused', 'пауза');
      } else {
        setStatus(state.connected ? 'live' : 'down', state.connected ? 'в эфире' : 'нет связи');
        loadState(); // подтягиваем данные, накопившиеся во время паузы
      }
    };
    $('pauseBtn').addEventListener('click', togglePause);

    $('unitsBtn').addEventListener('click', () => {
      state.bits = !state.bits;
      $('unitsBtn').textContent = state.bits ? 'бит/с' : 'Б/с';
      localStorage.setItem('netpulse.bits', String(state.bits));
      if (state.last) apply(state.last);
    });

    $('themeBtn').addEventListener('click', () => {
      const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
      document.documentElement.dataset.theme = next;
      localStorage.setItem('netpulse.theme', next);
    });

    $('rangeButtons').addEventListener('click', (event) => {
      const button = event.target.closest('button');
      if (!button) return;
      state.range = Number(button.dataset.range);
      [...event.currentTarget.children].forEach((b) => b.classList.toggle('is-active', b === button));
    });

    chart.addEventListener('mousemove', (event) => {
      const rect = chart.getBoundingClientRect();
      state.hover = { x: event.clientX - rect.left, y: event.clientY - rect.top };
    });
    chart.addEventListener('mouseleave', () => { state.hover = null; });

    document.addEventListener('keydown', (event) => {
      if (event.code === 'Space' && event.target === document.body) {
        event.preventDefault();
        togglePause();
      }
    });
  }

  function restorePreferences() {
    const theme = localStorage.getItem('netpulse.theme');
    if (theme) document.documentElement.dataset.theme = theme;
    if (localStorage.getItem('netpulse.bits') === 'true') {
      state.bits = true;
      $('unitsBtn').textContent = 'бит/с';
    }
  }

  // --------------------------------------------------------------- запуск

  function frame() {
    drawChart();
    drawSpark($('rxSpark'), 'rx_bps', css('--rx'));
    drawSpark($('txSpark'), 'tx_bps', css('--tx'));
    requestAnimationFrame(frame);
  }

  restorePreferences();
  bindControls();
  loadState().then(connect).catch(() => setStatus('down', 'сервер недоступен'));
  loadConnections();
  setInterval(loadConnections, 3000);
  requestAnimationFrame(frame);
})();
