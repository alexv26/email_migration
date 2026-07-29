(function () {
  const tbody = document.getElementById("jobs-body");

  function escapeHtml(s) {
    const div = document.createElement("div");
    div.textContent = s;
    return div.innerHTML;
  }

  function folderSummary(meta) {
    if (!meta || meta.total_folders === undefined) return "-";
    return (meta.folders_done || 0) + " / " + meta.total_folders + " folders";
  }

  function render(jobs) {
    if (!jobs.length) {
      tbody.innerHTML = '<tr><td colspan="5" class="hint">No active or recent jobs.</td></tr>';
      return;
    }

    tbody.innerHTML = jobs.map(function (job) {
      const meta = job.meta || {};
      return (
        "<tr>" +
        "<td>" + escapeHtml(job.job_id.slice(0, 8)) + "</td>" +
        "<td>" + escapeHtml(job.job_status) + "</td>" +
        "<td>" + escapeHtml(folderSummary(meta)) + "</td>" +
        "<td>" + escapeHtml(job.enqueued_at || "-") + "</td>" +
        "<td>" + escapeHtml(meta.error || "") + "</td>" +
        "</tr>"
      );
    }).join("");
  }

  function poll() {
    fetch("/admin/api/jobs", { headers: { Accept: "application/json" } })
      .then(function (res) {
        if (res.status === 401) {
          window.location.href = "/admin/login";
          return null;
        }
        return res.json();
      })
      .then(function (jobs) {
        if (jobs) render(jobs);
      })
      .catch(function () {
        // transient network hiccup - keep polling
      });
  }

  poll();
  setInterval(poll, 3000);
})();
