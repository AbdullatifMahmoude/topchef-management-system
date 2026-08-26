(function () {
  "use strict";

  window.createCashierLiveSocket = function createCashierLiveSocket(options) {
    let socket = null;
    let reconnectTimerId = null;
    let heartbeatTimerId = null;
    let watchdogTimerId = null;
    let reconnectAttempts = 0;
    let lastActivityAt = 0;

    function updateStatus(status) {
      const dot = document.getElementById("ws_status_dot");
      const text = document.getElementById("ws_status_text");
      if (!dot || !text) return;
      const states = {
        connected: ["#2ecc71", "متصل مباشر"],
        disconnected: ["#e74c3c", "غير متصل (إعادة محاولة)"],
        connecting: ["#f1c40f", "جاري الاتصال..."],
      };
      const [color, label] = states[status] || states.connecting;
      dot.style.background = color;
      text.textContent = label;
    }

    function stopHealthChecks() {
      if (heartbeatTimerId) clearInterval(heartbeatTimerId);
      if (watchdogTimerId) clearInterval(watchdogTimerId);
      heartbeatTimerId = null;
      watchdogTimerId = null;
    }

    function connect() {
      if (reconnectTimerId) {
        clearTimeout(reconnectTimerId);
        reconnectTimerId = null;
      }
      if (socket && [WebSocket.OPEN, WebSocket.CONNECTING].includes(socket.readyState)) return;

      updateStatus("connecting");
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const token = localStorage.getItem("token") || "";
      const ws = new WebSocket(`${protocol}//${window.location.host}${options.path}`, ["access_token", token]);
      socket = ws;

      const connectTimeoutId = setTimeout(() => {
        if (ws.readyState === WebSocket.CONNECTING) ws.close();
      }, options.connectTimeoutMs || 12000);

      ws.onopen = () => {
        clearTimeout(connectTimeoutId);
        stopHealthChecks();
        lastActivityAt = Date.now();
        heartbeatTimerId = setInterval(() => {
          if (socket === ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: "HEARTBEAT", sent_at: Date.now() }));
          }
        }, 15000);
        watchdogTimerId = setInterval(() => {
          if (socket === ws && ws.readyState === WebSocket.OPEN && Date.now() - lastActivityAt > 55000) {
            ws.close(4000, "heartbeat timeout");
          }
        }, 10000);
        updateStatus("connected");
        setTimeout(() => {
          if (socket === ws && ws.readyState === WebSocket.OPEN) reconnectAttempts = 0;
        }, 30000);
        if (options.onOpen) options.onOpen(ws);
      };

      ws.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          lastActivityAt = Date.now();
          if (payload.type === "HEARTBEAT") {
            if (ws.readyState === WebSocket.OPEN) {
              ws.send(JSON.stringify({ type: "HEARTBEAT_ACK", received_at: Date.now() }));
            }
            return;
          }
          if (options.onMessage) options.onMessage(payload);
        } catch (error) {
          console.error("Invalid WebSocket message", error);
        }
      };

      ws.onclose = (event) => {
        clearTimeout(connectTimeoutId);
        stopHealthChecks();
        if (socket !== ws) return;
        socket = null;
        updateStatus("disconnected");
        if (event.code === 4401 || event.code === 4403) {
          localStorage.removeItem("token");
          window.location.replace("../index.html");
          return;
        }
        reconnectAttempts += 1;
        const base = event.code === 1012 ? 1000 : Math.min(15000, 1000 * (2 ** Math.min(reconnectAttempts - 1, 4)));
        reconnectTimerId = setTimeout(() => {
          reconnectTimerId = null;
          if (navigator.onLine !== false) connect();
        }, base + Math.floor(Math.random() * 750));
      };

      ws.onerror = () => updateStatus("disconnected");
    }

    window.addEventListener("online", connect);
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) return;
      if (!socket || socket.readyState === WebSocket.CLOSED) connect();
      if (options.onVisible) options.onVisible();
    });

    return { connect, updateStatus };
  };
})();
