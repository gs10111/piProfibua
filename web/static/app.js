import { h, render } from "preact";
import { useState, useEffect, useRef } from "preact/hooks";
import htm from "htm";

const html = htm.bind(h);

function useSocket() {
  const [snap, setSnap] = useState({ connected: false, diag: "conectando", angle_deg: 0,
    raw: 0, raw_max: 8191, bytes_hex: "", offset: 0, rate_hz: 0 });
  const ws = useRef(null);
  useEffect(() => {
    let stop = false;
    function connect() {
      if (stop) return;
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const s = new WebSocket(`${proto}://${location.host}/ws`);
      ws.current = s;
      s.onmessage = (e) => setSnap(JSON.parse(e.data));
      s.onclose = () => { if (!stop) setTimeout(connect, 800); };
    }
    connect();
    return () => { stop = true; ws.current && ws.current.close(); };
  }, []);
  const send = (cmd) => ws.current && ws.current.readyState === 1 && ws.current.send(JSON.stringify({ cmd }));
  return { snap, send };
}

function App() {
  const { snap, send } = useSocket();
  const live = snap.connected;
  const angle = Number(snap.angle_deg || 0);
  return html`
    <div class="panel">
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
        <button onClick=${() => send("zero")}>Zerar aqui</button>
        <button class="ghost" onClick=${() => send("clear_zero")}>Desfazer</button>
      </div>
    </div>`;
}

render(html`<${App} />`, document.getElementById("app"));
