const $ = (id) => document.getElementById(id);

function log(msg) {
  const el = $("actionLog");
  const line = `[${new Date().toLocaleTimeString()}] ${msg}`;
  el.textContent = el.textContent ? `${el.textContent}\n${line}` : line;
  el.scrollTop = el.scrollHeight;
}

async function getJSON(url, opts) {
  const res = await fetch(url, opts);
  const text = await res.text();
  let data;
  try { data = text ? JSON.parse(text) : {}; }
  catch { data = { raw: text }; }
  if (!res.ok) throw new Error(data.detail || data.error || res.statusText || String(res.status));
  return data;
}

function setPill(id, ok, label) {
  const el = $(id);
  el.textContent = label;
  el.classList.toggle("ok", !!ok);
  el.classList.toggle("bad", !ok);
}

async function refreshHealth() {
  try {
    const h = await getJSON("/api/health");
    setPill("healthPill", true, `API ${h.status}`);
  } catch (e) {
    setPill("healthPill", false, "API down");
  }
  try {
    const c = await getJSON("/api/config");
    $("configBox").textContent = JSON.stringify(c, null, 2);
    if (!$("topic").value && c.topic) $("topic").value = c.topic;
    setPill("llmPill", true, `${c.mode} · ${c.project}`);
  } catch (e) {
    setPill("llmPill", false, "config error");
  }
}

async function refreshStatus() {
  try {
    const s = await getJSON("/api/pipeline/status");
    $("runStatus").textContent = s.status || "idle";
    $("runId").textContent = s.run_id || "—";
    $("runTopic").textContent = s.topic || "—";
    $("runOut").textContent = s.output_dir || "—";
    const running = s.status === "running";
    $("startBtn").disabled = running;
    $("stopBtn").disabled = !running;
  } catch (e) {
    $("runStatus").textContent = "error";
  }
}

async function refreshStages() {
  try {
    const data = await getJSON("/api/pipeline/stages");
    const root = $("stages");
    root.innerHTML = "";
    for (const s of data.stages || []) {
      const div = document.createElement("div");
      div.className = "stage";
      div.innerHTML = `<strong>${s.number}. ${s.phase || ""}</strong>${s.name}`;
      root.appendChild(div);
    }
  } catch (e) {
    $("stages").textContent = "Could not load stages.";
  }
}

async function refreshRuns() {
  try {
    const data = await getJSON("/api/runs");
    const ul = $("runs");
    ul.innerHTML = "";
    const runs = data.runs || [];
    if (!runs.length) {
      ul.innerHTML = "<li>No runs yet.</li>";
      return;
    }
    for (const r of runs.slice(0, 12)) {
      const li = document.createElement("li");
      li.innerHTML = `<code>${r.run_id}</code><span>${r.path || ""}</span>`;
      ul.appendChild(li);
    }
  } catch (e) {
    $("runs").innerHTML = "<li>Could not load runs.</li>";
  }
}

$("startBtn").addEventListener("click", async () => {
  const topic = $("topic").value.trim();
  if (!topic) {
    log("Enter a research topic first.");
    return;
  }
  try {
    log(`Starting pipeline: ${topic}`);
    const res = await getJSON("/api/pipeline/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        topic,
        auto_approve: $("autoApprove").checked,
      }),
    });
    log(`Started ${res.run_id} → ${res.output_dir}`);
    await refreshStatus();
    await refreshRuns();
  } catch (e) {
    log(`Start failed: ${e.message}`);
  }
});

$("stopBtn").addEventListener("click", async () => {
  try {
    await getJSON("/api/pipeline/stop", { method: "POST" });
    log("Stop requested.");
    await refreshStatus();
  } catch (e) {
    log(`Stop failed: ${e.message}`);
  }
});

(async function boot() {
  await refreshHealth();
  await refreshStages();
  await refreshStatus();
  await refreshRuns();
  setInterval(async () => {
    await refreshHealth();
    await refreshStatus();
    await refreshRuns();
  }, 3000);
})();
