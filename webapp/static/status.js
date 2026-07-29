(function () {
  const script = document.currentScript;
  const jobId = script.dataset.jobId;

  const jobStateEl = document.getElementById("job-state");
  const overallBarEl = document.getElementById("overall-bar");
  const overallCountEl = document.getElementById("overall-count");
  const foldersEl = document.getElementById("folders");
  const errorEl = document.getElementById("error");

  const folderBars = {};
  let sawTerminal = false;
  let timer = null;

  function ensureFolderBar(name) {
    if (folderBars[name]) return folderBars[name];

    const row = document.createElement("div");
    row.className = "bar-row";
    row.innerHTML =
      '<span class="bar-label" title="' + name + '">' + name + '</span>' +
      '<div class="bar"><div class="bar-fill" style="width:0%"></div></div>' +
      '<span class="bar-count"></span>';
    foldersEl.appendChild(row);

    const entry = {
      fill: row.querySelector(".bar-fill"),
      count: row.querySelector(".bar-count"),
    };
    folderBars[name] = entry;
    return entry;
  }

  function pct(done, total) {
    if (!total) return 0;
    return Math.min(100, Math.round((done / total) * 100));
  }

  function render(meta) {
    const totalFolders = meta.total_folders || 0;
    const foldersDone = meta.folders_done || 0;
    overallBarEl.style.width = pct(foldersDone, totalFolders) + "%";
    overallCountEl.textContent = foldersDone + " / " + totalFolders;

    const folders = meta.folders || {};
    Object.keys(folders).forEach(function (name) {
      const info = folders[name];
      const bar = ensureFolderBar(name);
      bar.fill.style.width = pct(info.done, info.total) + "%";
      bar.count.textContent = info.done + " / " + info.total;
    });
  }

  function stopPolling() {
    if (timer) clearInterval(timer);
  }

  function poll() {
    fetch("/api/status/" + jobId, { headers: { Accept: "application/json" } })
      .then(function (res) {
        if (res.status === 404) {
          if (sawTerminal) {
            jobStateEl.textContent = "Done - job data cleaned up.";
          } else {
            jobStateEl.textContent = "Job not found.";
          }
          stopPolling();
          return null;
        }
        return res.json();
      })
      .then(function (data) {
        if (!data) return;

        if (data.job_status === "gone") {
          jobStateEl.textContent = "Done - job data cleaned up.";
          stopPolling();
          return;
        }

        if (data.meta) render(data.meta);

        if (data.job_status === "finished") {
          jobStateEl.textContent = "Migration complete.";
          sawTerminal = true;
          stopPolling();
        } else if (data.job_status === "failed") {
          jobStateEl.textContent = "Migration failed.";
          errorEl.hidden = false;
          errorEl.textContent = (data.meta && data.meta.error) || "An error occurred.";
          sawTerminal = true;
          stopPolling();
        } else if (data.job_status === "queued" || data.job_status === "deferred" || data.job_status === "scheduled") {
          jobStateEl.textContent = "Waiting in queue - another migration is running first…";
        } else {
          jobStateEl.textContent = "Running…";
        }
      })
      .catch(function () {
        // Transient network hiccup - keep polling, don't surface as fatal.
      });
  }

  poll();
  timer = setInterval(poll, 2000);
})();
