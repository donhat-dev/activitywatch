(function () {
  const url = new URL(window.location.href);
  const statusEl = document.getElementById("status");
  const summaryEl = document.getElementById("summary");
  const galleryEl = document.getElementById("gallery");

  const hostname = url.searchParams.get("hostname");
  const port = url.port || (url.protocol === "https:" ? "443" : "80");
  const todayStart = new Date();
  todayStart.setHours(0, 0, 0, 0);
  const todayEnd = new Date();
  todayEnd.setHours(23, 59, 59, 999);

  const start = url.searchParams.get("start") || todayStart.toISOString();
  const end = url.searchParams.get("end") || todayEnd.toISOString();
  let bucketId = null;
  const apiBase = `${url.origin}/api/0`;

  function setStatus(message) {
    statusEl.textContent = message;
  }

  function formatTime(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return value;
    }
    return date.toLocaleString();
  }

  function assetUrl(eventId, assetIndex) {
    return `${apiBase}/buckets/${encodeURIComponent(bucketId)}/events/${eventId}/assets/${assetIndex}`;
  }

  function pickBucketId(buckets) {
    const ids = Object.keys(buckets || {});
    const preferredIds = [];

    if (hostname) {
      preferredIds.push(`aw-watcher-screenshot-mini_${hostname}`);
    }
    preferredIds.push("aw-watcher-screenshot-mini");

    for (const id of preferredIds) {
      if (buckets[id]) {
        return id;
      }
    }

    const fallback = ids.find((id) => {
      const bucket = buckets[id];
      return bucket && bucket.type === "os.desktop.screenshot";
    });

    return fallback || null;
  }

  function render(events) {
    const imageEntries = [];
    for (const event of events) {
      const images = Array.isArray(event.data && event.data.images) ? event.data.images : [];
      images.forEach((image, index) => {
        imageEntries.push({
          eventId: event.id,
          assetIndex: index,
          timestamp: event.timestamp || (event.data && event.data.captured_at),
          backend: event.data && event.data.backend,
          monitorId: image.monitor_id || `display-${index}`,
          bytes: image.bytes,
          uploaded: image.uploaded,
          sha256: image.sha256,
        });
      });
    }

    imageEntries.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));

    summaryEl.hidden = false;
    summaryEl.innerHTML = `Bucket: <strong>${bucketId}</strong><br>Total events: <strong>${events.length}</strong><br>Total images: <strong>${imageEntries.length}</strong><br>Range: <strong>${formatTime(start)}</strong> → <strong>${formatTime(end)}</strong>`;

    if (!imageEntries.length) {
      setStatus("No screenshots found in the selected range.");
      return;
    }

    setStatus(`Loaded ${imageEntries.length} screenshot(s) from ${events.length} event(s).`);

    const fragment = document.createDocumentFragment();
    imageEntries.forEach((entry) => {
      const card = document.createElement("article");
      card.className = "card";

      const link = document.createElement("a");
      link.href = assetUrl(entry.eventId, entry.assetIndex);
      link.target = "_blank";
      link.rel = "noreferrer noopener";

      const img = document.createElement("img");
      img.loading = "lazy";
      img.alt = `${entry.monitorId} at ${formatTime(entry.timestamp)}`;
      img.src = link.href;
      link.appendChild(img);

      const body = document.createElement("div");
      body.className = "card-body";
      body.innerHTML = `
        <div><strong>${entry.monitorId}</strong></div>
        <div class="meta">${formatTime(entry.timestamp)}</div>
        <div class="meta">backend: ${entry.backend || "unknown"}</div>
        <div class="meta">size: ${entry.bytes || 0} bytes</div>
        <div class="meta">uploaded: ${entry.uploaded ? "yes" : "no"}</div>
        <div class="meta">sha256: ${(entry.sha256 || "").slice(0, 16) || "n/a"}</div>
      `;

      card.appendChild(link);
      card.appendChild(body);
      fragment.appendChild(card);
    });

    galleryEl.replaceChildren(fragment);
  }

  async function load() {
    try {
      const bucketsResponse = await fetch(`${apiBase}/buckets/`);
      if (!bucketsResponse.ok) {
        throw new Error(`Failed to load buckets (${bucketsResponse.status})`);
      }
      const buckets = await bucketsResponse.json();

      bucketId = pickBucketId(buckets);
      if (!bucketId) {
        throw new Error(
          hostname
            ? `No screenshot bucket found for host ${hostname}`
            : "No screenshot bucket found"
        );
      }

      const params = new URLSearchParams({ start, end, limit: "200" });
      const eventsResponse = await fetch(
        `${apiBase}/buckets/${encodeURIComponent(bucketId)}/events?${params.toString()}`
      );
      if (!eventsResponse.ok) {
        throw new Error(`Failed to load events (${eventsResponse.status})`);
      }

      const events = await eventsResponse.json();
      render(events);
    } catch (error) {
      setStatus(error && error.message ? error.message : String(error));
    }
  }

  if (port !== "5600") {
    document.body.dataset.testing = "true";
  }

  load();
})();