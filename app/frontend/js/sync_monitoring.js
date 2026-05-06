// ============================================
// Sync Monitoring & Events Page Logic
// ============================================
async function refreshSyncStatus() {
  const container = document.getElementById("sync_stats_container");
  if (!container) return;

  container.innerHTML = '<p style="color:var(--color-primary); text-align:center; grid-column: 1/-1; padding: 40px;">جاري جلب بيانات المزامنة...</p>';

  try {
    const res = await window.apiFetch("/desktop-updates/sync/status", { hideLoader: true });
    if (!res.ok) throw new Error("فشل تحميل الحالة");
    const data = await res.json();

    renderSyncStatus(data);
  } catch (err) {
    console.error(err);
    container.innerHTML = '<p style="color:#e74c3c; text-align:center; grid-column: 1/-1; padding: 40px;">فشل تحميل بيانات المزامنة. تأكد من اتصالك بالسيرفر.</p>';
  }
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

    cards.forEach(c => {
      const card = document.createElement("div");
      card.className = "card";
      card.innerHTML = `
                <h1>${c.title}</h1>
                <h2 style="color:${c.color}">${c.value}</h2>
                <span style="opacity:0.7">${c.label}</span>
            `;
      container.appendChild(card);
    });

    if (data.failed_events && data.failed_events.length > 0) {
      if (failedSection) failedSection.style.display = "block";
      const tbody = document.querySelector("#failed_events_table tbody");
      if (tbody) {
        tbody.innerHTML = data.failed_events.map(e => `
                <tr>
                    <td>#${e.id}</td>
                    <td><span style="font-size:11px; font-weight:bold;">${e.event_type}</span></td>
                    <td>${e.topic || '---'}</td>
                    <td style="color:#e74c3c; font-size:10px; max-width: 300px; line-height:1.2;">${e.error || 'خطأ غير معروف'}</td>
                    <td style="text-align:center">${e.retry_count}</td>
                    <td><span style="font-size:11px; opacity:0.8;">${new Date(e.created_at).toLocaleString('ar-EG', {hour:'2-digit', minute:'2-digit', second:'2-digit'})}</span></td>
                </tr>
            `).join("");
      }
    }
  } else {
    if (cloudSection) cloudSection.style.display = "block";
    const tbody = document.querySelector("#device_stats_table tbody");
    const devices = Object.entries(data.device_stats || {});

    if (tbody) {
      if (devices.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; padding:40px; opacity:0.5;">لا توجد بيانات أجهزة مسجلة في السحابة حتى الآن</td></tr>';
      } else {
        tbody.innerHTML = data.device_stats.map(dev => {
          const lastSeen = new Date(dev.last_seen);
          const diff = (new Date() - lastSeen) / 1000;
          const isOnline = diff < 120; // 2 minutes threshold
          
          return `
                <tr>
                    <td style="font-family: monospace; font-size:12px; color:var(--color-primary);">
                        ${dev.device_id}
                        <br><span style="font-size:10px; opacity:0.6;">v${dev.version || '?.?'}</span>
                    </td>
                    <td style="font-weight: bold; font-size:16px;">${dev.count}</td>
                    <td style="font-size:11px; opacity:0.8;">${lastSeen.toLocaleTimeString('ar-EG')}</td>
                    <td><span class="${isOnline ? 'status_completed' : 'status_cancelled'}">${isOnline ? 'متصل' : 'غير متصل'}</span></td>
                </tr>
            `;
        }).join("");
      }
    }
    
    // Add a placeholder card for cloud mode
    const card = document.createElement("div");
    card.className = "card";
    card.style.gridColumn = "1/-1";
    card.innerHTML = `
        <h1>إجمالي الأجهزة النشطة</h1>
        <h2>${devices.length}</h2>
        <span>أجهزة POS مرتبطة بالسحابة</span>
    `;
    container.appendChild(card);
  }
}
