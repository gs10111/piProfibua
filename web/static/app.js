import { h, render } from "preact";
import { useState, useEffect, useRef } from "preact/hooks";
import htm from "htm";

const html = htm.bind(h);

const BAUDS = [9600, 19200, 45450, 93750, 187500, 500000, 1500000];
const RELIABLE = [9600, 19200];

// Decodifica os bytes crus do encoder (big-endian PROFIBUS) em volta + ângulo.
// stepsPerTurn = resolução singleturn (RM3007 = 8192). 4 bytes => multivolta.
function decodePosition(hex, stepsPerTurn) {
  if (!hex || hex.length < 2) return null;
  const spt = stepsPerTurn > 0 ? stepsPerTurn : 8192;
  const value = parseInt(hex, 16);          // 1..4 bytes, MSB primeiro
  if (!Number.isFinite(value)) return null;
  const single = ((value % spt) + spt) % spt;
  return {
    value, single, stepsPerTurn: spt,
    turns: Math.floor(value / spt),
    angle: (single / spt) * 360,
    multiturn: hex.length / 2 >= 4,
  };
}

function useBusSocket() {
  const [encoder, setEncoder] = useState({ connected: false, diag: "conectando",
    angle_deg: 0, raw: 0, raw_max: 8191, bytes_hex: "", offset: 0, rate_hz: 0 });
  const [bus, setBus] = useState({ mode: "exchange", diag: "ok",
    settings: { baud: 19200, master_addr: 1 },
    scan: { status: "idle", current_addr: null, scanned: 0, total: 0, found: [] } });
  const [io, setIo] = useState({ active: false, address: 0, connected: false,
    diag: "", in_hex: "", out_hex: "", input_size: 0, output_size: 0, rate_hz: 0 });
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
        else if (m.type === "io") setIo(m);
      };
      s.onclose = () => { if (!stop) setTimeout(connect, 800); };
    }
    connect();
    return () => { stop = true; ws.current && ws.current.close(); };
  }, []);
  const send = (obj) => ws.current && ws.current.readyState === 1 &&
    ws.current.send(JSON.stringify(obj));
  return { encoder, bus, io, send };
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

function GsdView({ io, bus, send }) {
  const [list, setList] = useState([]);
  const [sel, setSel] = useState(null);
  const [chosen, setChosen] = useState([]);
  const [preview, setPreview] = useState(null);
  const [err, setErr] = useState("");
  const [addr, setAddr] = useState(3);
  const [outHex, setOutHex] = useState("");
  const [spt, setSpt] = useState(8192);   // passos/volta (RM3007 = 8192)
  const refresh = () => fetch("/api/gsd").then((r) => r.json())
    .then((d) => setList(d.gsds || [])).catch(() => {});
  useEffect(() => { refresh(); }, []);
  const open = (name) => fetch(`/api/gsd/${name}`).then((r) => r.json())
    .then((d) => { setSel(d); setChosen([]); setPreview(null); });
  const runPreview = (mods) => fetch(`/api/gsd/${sel.filename}/preview`,
    { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ modules: mods }) })
    .then((r) => r.json()).then(setPreview).catch(() => {});
  const toggle = (name) => {
    const next = chosen.includes(name) ? chosen.filter((x) => x !== name) : [...chosen, name];
    setChosen(next);
    if (sel) runPreview(next);
  };
  const upload = (file) => {
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    setErr("");
    fetch("/api/gsd", { method: "POST", body: fd }).then(async (r) => {
      const d = await r.json();
      if (!r.ok) { setErr(d.error || "falha no upload"); return; }
      refresh();
      open(d.filename);
    }).catch(() => setErr("falha de rede"));
  };
  // módulo só-leitura (mestre escreve 0) não roda no pyprofibus -> orienta antes do clique
  const readonly = preview && chosen.length > 0 && preview.out_size === 0;
  // erros de parametrização viram diag do barramento; espelha aqui na aba GSD
  const paramErr = bus && bus.diag && bus.diag.indexOf("parametrizar") >= 0 ? bus.diag : "";
  return html`
    <div class="view gsd">
      <div class="controls">
        <label>Enviar GSD
          <input type="file" accept=".gsd"
                 onChange=${(e) => upload(e.target.files[0])} />
        </label>
      </div>
      ${err ? html`<p class="warn">${err}</p>` : ""}
      <table class="stations">
        <thead><tr><th>Arquivo</th><th>Modelo</th><th>Ident</th></tr></thead>
        <tbody>
          ${list.map((g) => html`<tr class="clickable" onClick=${() => open(g.filename)}>
            <td>${g.filename}</td><td>${g.model || "--"}</td><td>${g.ident_hex || "--"}</td></tr>`)}
        </tbody>
      </table>
      ${list.length === 0 ? html`<p class="muted">Nenhum GSD enviado ainda.</p>` : ""}
      ${sel ? html`
        <div class="inspector">
          <div class="rows">
            <div>fabricante <b>${sel.vendor}</b></div>
            <div>modelo <b>${sel.model}</b></div>
            <div>ident <b>${sel.ident_hex}</b></div>
            <div>tipo <b>${sel.modular ? "modular" : "compacto"}${sel.dpv1 ? " · DPV1" : ""}</b></div>
          </div>
          <div class="muted">Módulos (escolha para ver a parametrização):</div>
          <div class="modlist">
            ${(sel.modules || []).filter((m) => !m.preset).map((m) => html`
              <label class="mod"><input type="checkbox" checked=${chosen.includes(m.name)}
                onChange=${() => toggle(m.name)} /> ${m.name}</label>`)}
          </div>
          ${preview ? html`
            <div class="rows">
              <div>ident <b>${preview.ident_hex}</b></div>
              <div>cfg (Chk_Cfg) <b>${preview.cfg_hex || "--"}</b></div>
              <div>user_prm (Set_Prm) <b>${preview.user_prm_hex || "--"}</b></div>
              <div>lê / escreve <b>${preview.in_size} B / ${preview.out_size} B</b></div>
            </div>` : ""}
          <div class="controls">
            <label>Endereço<input type="number" min="1" max="126" value=${addr}
              onInput=${(e) => setAddr(Number(e.target.value))} /></label>
            <button disabled=${chosen.length === 0 || readonly}
              onClick=${() => send({ cmd: "param_read", gsd: sel.filename,
              address: addr, modules: chosen })}>
              Parametrizar e ler</button>
          </div>
          ${readonly ? html`<p class="warn">Class 1 é o perfil correto do encoder, mas o
            pyprofibus não consegue pollar escravo só-leitura (mestre escreve 0 B). Para ler a
            <b>mesma</b> posição, use <b>Class 2 Multiturn</b> (4 B de saída zerados, sem preset).</p>` : ""}
          ${paramErr ? html`<p class="warn">${paramErr}</p>` : ""}
          <p class="muted">Os tamanhos de I/O são derivados do(s) módulo(s) escolhido(s)
            (cfg byte). Chegar ao Data_Exchange depende de baterem com o escravo;
            senão, o diag aparece abaixo.</p>
        </div>` : ""}
      ${io.active ? (() => {
        const pos = decodePosition(io.in_hex, spt);
        const live = io.connected && pos;
        return html`
        <div class="io-panel">
          <div class="top">
            <div class="title">Encoder · addr ${io.address}</div>
            <div class="badge"><span class=${"dot" + (io.connected ? " on" : "")}></span>
              ${io.connected ? `${(io.rate_hz || 0).toFixed(0)} Hz` : (io.diag || "conectando")}</div>
          </div>
          ${pos ? html`
            <div class="gauge">
              <div class="ring"></div>
              <div class="needle" style=${`transform:translate(-50%,-100%) rotate(${pos.angle}deg)`}></div>
              <div class="hub"></div>
              <div class="val"><div class=${"deg" + (live ? "" : " stale")}>${pos.angle.toFixed(1)}°</div></div>
            </div>
            <div class="rows">
              <div>voltas <b>${pos.multiturn ? pos.turns : "—"}</b></div>
              <div>na volta <b>${pos.single} / ${pos.stepsPerTurn}</b></div>
              <div>posição <b>${pos.value}</b></div>
              <div>bytes <b>${io.in_hex || "--"}</b></div>
            </div>` : html`
            <div class="rows">
              <div>entrada <b>${io.in_hex || "--"}</b></div>
              <div>diag <b>${io.diag}</b></div>
            </div>`}
          <div class="controls">
            <label>passos/volta<input type="number" min="1" value=${spt}
              onInput=${(e) => setSpt(Number(e.target.value))} /></label>
            <label>Saída (hex)<input value=${outHex}
              onInput=${(e) => setOutHex(e.target.value)}
              placeholder=${"00".repeat(io.output_size)} /></label>
            <button onClick=${() => send({ cmd: "set_output", hex: outHex })}>Enviar saída</button>
            <button class="ghost" onClick=${() => send({ cmd: "stop_generic" })}>Parar</button>
          </div>
        </div>`;
      })() : ""}
    </div>`;
}

function App() {
  const { encoder, bus, io, send } = useBusSocket();
  const [tab, setTab] = useState("encoder");
  const view = tab === "encoder"
    ? html`<${EncoderView} snap=${encoder} send=${send} />`
    : tab === "bus"
      ? html`<${BusView} bus=${bus} send=${send} />`
      : html`<${GsdView} io=${io} bus=${bus} send=${send} />`;
  return html`
    <div class="panel">
      <nav class="tabs">
        <button class=${"tab" + (tab === "encoder" ? " active" : "")}
                onClick=${() => setTab("encoder")}>Encoder</button>
        <button class=${"tab" + (tab === "bus" ? " active" : "")}
                onClick=${() => setTab("bus")}>Barramento</button>
        <button class=${"tab" + (tab === "gsd" ? " active" : "")}
                onClick=${() => setTab("gsd")}>GSD</button>
      </nav>
      ${view}
    </div>`;
}

const root = document.getElementById("app");
root.innerHTML = "";  // remove o placeholder "carregando…" (Preact não limpa container não-vazio)
render(html`<${App} />`, root);
