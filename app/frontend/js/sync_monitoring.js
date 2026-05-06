// ============================================
// Sync Monitoring & Events Page Logic
// ============================================
async function refreshSyncStatus() {
  const container = document.getElementById("sync_stats_container");
  if (!container) return;

  container.innerHTML = '<p style="color:var(--color-primary); text-align:center; grid-column:1/-1; padding:40px;">جاري جلب بيانات المزامنة...</p>';

  try {
    const res = await window.apiFetch("/desktop-updates/sync/status", { hideLoader: true });
    if (!res.ok) throw new Error("فشل تحميل الحالة");
    const data = await res.json();
    renderSyncStatus(data);
  } catch (err) {
    console.error(err);
    container.innerHTML = '<p style="color:#e74c3c; text-align:center; grid-column:1/-1; padding:40px;">فشل تحميل بيانات المزامنة. تأكد من اتصالك بالسيرفر.</p>';
  }
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function formatLastSeen(value) {
  if (!value) return "---";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "---";
  return date.toLocaleString("ar-EG", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    day: "2-digit",
    month: "2-digit"
  });
}

function renderSyncStatus(data) {
  const container = document.getElementById("sync_stats_container");
  const failedSection = document.getElementById("failed_events_section");
  const cloudSection = document.getElementById("cloud_device_stats");

  if (!container) return;

  container.innerHTML = "";
  if (failedSection) failedSection.style.display = "none";
  if (cloudSection) cloudSection.style.display = "none";

  if (data.mode === "desktop") {
    const stats = data.stats || {};
    const cards = [
      { title: "قيد المزامنة", value: stats.PENDING || 0, color: "var(--color-primary)", label: "حدث معلق" },
      { title: "فشلت المزامنة", value: stats.FAILED || 0, color: "#e74c3c", label: "تحتاج مراجعة" },
      { title: "تمت بنجاح", value: stats.COMPLETED || 0, color: "#2ecc71", label: "حدث مكتمل" }
    ];

    cards.forEach((cardData) => {
      const card = document.createElement("div");
      card.className = "card";
      card.innerHTML = `
        <h1>${cardData.title}</h1>
        <h2 style="color:${cardData.color}">${cardData.value}</h2>
        <span style="opacity:0.7">${cardData.label}</span>
      `;
      container.appendChild(card);
    });

    if (data.failed_events && data.failed_events.length > 0) {
      if (failedSection) failedSection.style.display = "block";
      const tbody = document.querySelector("#failed_events_table tbody");
      if (tbody) {
        tbody.innerHTML = data.failed_events.map((eventItem) => `
          <tr>
            <td>#${eventItem.id}</td>
            <td><span style="font-size:11px; font-weight:bold;">${escapeHtml(eventItem.event_type)}</span></td>
            <td>${escapeHtml(eventItem.topic || "---")}</td>
            <td style="color:#e74c3c; font-size:10px; max-width:300px; line-height:1.2;">${escapeHtml(eventItem.error || "خطأ غير معروف")}</td>
            <td style="text-align:center">${eventItem.retry_count}</td>
            <td><span style="font-size:11px; opacity:0.8;">${formatLastSeen(eventItem.created_at)}</span></td>
          </tr>
        `).join("");
      }
    }
    return;
  }

  if (cloudSection) cloudSection.style.display = "block";

  const headerRow = document.querySelector("#device_stats_table thead tr");
  if (headerRow) {
    headerRow.innerHTML = "<th>معرف الجهاز</th><th>إجمالي الأحداث المستلمة</th><th>آخر ظهور</th><th>الحالة</th>";
  }

  const tbody = document.querySelector("#device_stats_table tbody");
  const devices = Array.isArray(data.device_stats) ? data.device_stats : [];

  if (tbody) {
    if (devices.length === 0) {
      tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; padding:40px; opacity:0.5;">لا توجد أجهزة أرسلت heartbeat حتى الآن</td></tr>';
    } else {
      tbody.innerHTML = devices.map((device) => {
        const ipLabel = device.ip_address ? " · " + escapeHtml(device.ip_address) : "";
        return `
          <tr>
            <td style="font-family:monospace; font-size:12px; color:var(--color-primary); line-height:1.6;">
              ${escapeHtml(device.device_id)}
              <br><span style="font-size:10px; opacity:0.6;">v${escapeHtml(device.version || "?.?")}${ipLabel}</span>
            </td>
            <td style="font-weight:bold; font-size:16px;">${device.count || 0}</td>
            <td style="font-size:11px; opacity:0.8;">${formatLastSeen(device.last_seen)}</td>
            <td><span class="${device.online ? "status_completed" : "status_cancelled"}">${device.online ? "متصل الآن" : "غير متصل"}</span></td>
          </tr>
        `;
      }).join("");
    }
  }

  const card = document.createElement("div");
  card.className = "card";
  card.style.gridColumn = "1/-1";
  card.innerHTML = `
    <h1>الأجهزة المتصلة الآن</h1>
    <h2>${data.online_devices || 0} / ${data.total_devices || devices.length}</h2>
    <span>أجهزة POS المتصلة حاليا / جميع الأجهزة المعروفة</span>
  `;
  container.appendChild(card);
}
