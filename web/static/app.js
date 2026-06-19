import { h, render } from "preact";
import { useState, useEffect, useRef } from "preact/hooks";
import htm from "htm";

const html = htm.bind(h);

const BAUDS = [9600, 19200, 45450, 93750, 187500, 500000, 1500000];
const RELIABLE = [9600, 19200];

function useBusSocket() {
  const [encoder, setEncoder] = useState({ connected: false, diag: "conectando",
    angle_deg: 0, raw: 0, raw_max: 8191, bytes_hex: "", offset: 0, rate_hz: 0 });
  const [bus, setBus] = useState({ mode: "exchange", diag: "ok",
    settings: { baud: 19200, master_addr: 1 },
    scan: { status: "idle", current_addr: null, scanned: 0, total: 0, found: [] } });
  const ws = useRef(null);
  useEffect(() => {
    let stop = false;
    function connect() {
      if (stop) return;
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const s = new WebSocket(`${proto}://${location.host}/ws`);
      ws.current = s;
      s.onmessage = (e) => {
        const m = JSON.parse(e.data);
        if (m.type === "reading") setEncoder(m);
        else if (m.type === "bus") setBus(m);
      };
      s.onclose = () => { if (!stop) setTimeout(connect, 800); };
    }
    connect();
    return () => { stop = true; ws.current && ws.current.close(); };
  }, []);
  const send = (obj) => ws.current && ws.current.readyState === 1 &&
    ws.current.send(JSON.stringify(obj));
  return { encoder, bus, send };
}

function EncoderView({ snap, send }) {
  const live = snap.connected;
  const angle = Number(snap.angle_deg || 0);
  return html`
    <div class="view">
      <div class="top">
        <div class="title">PROFIBUS · AMG11</div>
        <div class="badge"><span class=${"dot" + (live ? " on" : "")}></span>
          ${live ? `${(snap.rate_hz || 0).toFixed(0)} Hz` : (snap.diag || "sem leitura")}</div>
      </div>
      <div class="gauge">
        <div class="ring"></div>
        <div class="needle" style=${`transform:translate(-50%,-100%) rotate(${angle}deg)`}></div>
        <div class="hub"></div>
        <div class="val"><div class=${"deg" + (live ? "" : " stale")}>${angle.toFixed(1)}°</div></div>
      </div>
      <div class="rows">
        <div>bruto <b>${snap.raw} / ${snap.raw_max}</b></div>
        <div>bytes <b>${snap.bytes_hex || "--"}</b></div>
        <div>offset <b>${snap.offset}</b></div>
        <div>diag <b>${snap.diag}</b></div>
      </div>
      <div class="actions">
        <button onClick=${() => send({ cmd: "zero" })}>Zerar aqui</button>
        <button class="ghost" onClick=${() => send({ cmd: "clear_zero" })}>Desfazer</button>
      </div>
    </div>`;
}

function BusView({ bus, send }) {
  const s = bus.scan || {};
  const scanning = bus.mode === "scanning" || s.status === "scanning";
  const [baud, setBaud] = useState(bus.settings.baud);
  const [addr, setAddr] = useState(bus.settings.master_addr);
  useEffect(() => { setBaud(bus.settings.baud); setAddr(bus.settings.master_addr); },
    [bus.settings.baud, bus.settings.master_addr]);
  const pct = s.total ? Math.round((100 * s.scanned) / s.total) : 0;
  const found = s.found || [];
  return html`
    <div class="view bus">
      <div class="controls">
        <label>Baud
          <select value=${baud} onChange=${(e) => setBaud(Number(e.target.value))}>
            ${BAUDS.map((b) => html`<option value=${b}>${b}${RELIABLE.includes(b) ? "" : " (best-effort)"}</option>`)}
          </select>
        </label>
        <label>Endereço do mestre
          <input type="number" min="1" max="126" value=${addr}
                 onInput=${(e) => setAddr(Number(e.target.value))} />
        </label>
        <button onClick=${() => send({ cmd: "apply_settings", baud, master_addr: addr })}>Aplicar</button>
      </div>
      ${!RELIABLE.includes(baud) ? html`<p class="warn">No Raspberry Pi (Linux não-RT) via pyprofibus, só 9600 e 19200 são confiáveis. Acima disso o timing de slot tende a falhar (best-effort).</p>` : ""}
      <div class="scanbar">
        <button onClick=${() => send({ cmd: "scan" })} disabled=${scanning}>
          ${scanning ? "Varrendo..." : "Varrer"}</button>
        ${scanning ? html`
          <div class="prog"><div class="bar" style=${`width:${pct}%`}></div></div>
          <span class="muted">${s.scanned}/${s.total}${s.current_addr != null ? ` · addr ${s.current_addr}` : ""}</span>` : ""}
      </div>
      <table class="stations">
        <thead><tr><th>Endereço</th><th>Tipo</th><th>ms</th></tr></thead>
        <tbody>
          ${found.map((st) => html`<tr><td>${st.addr}</td><td>${st.station_type}</td><td>${st.response_ms}</td></tr>`)}
        </tbody>
      </table>
      ${s.status === "done" && found.length === 0 ? html`<p class="muted">Nenhuma estação respondeu.</p>` : ""}
      ${s.status === "idle" ? html`<p class="muted">Ainda não varrido.</p>` : ""}
      ${bus.diag && bus.diag !== "ok" ? html`<p class="warn">${bus.diag}</p>` : ""}
    </div>`;
}

function App() {
  const { encoder, bus, send } = useBusSocket();
  const [tab, setTab] = useState("encoder");
  return html`
    <div class="panel">
      <nav class="tabs">
        <button class=${"tab" + (tab === "encoder" ? " active" : "")}
                onClick=${() => setTab("encoder")}>Encoder</button>
        <button class=${"tab" + (tab === "bus" ? " active" : "")}
                onClick=${() => setTab("bus")}>Barramento</button>
      </nav>
      ${tab === "encoder"
        ? html`<${EncoderView} snap=${encoder} send=${send} />`
        : html`<${BusView} bus=${bus} send=${send} />`}
    </div>`;
}

render(html`<${App} />`, document.getElementById("app"));
