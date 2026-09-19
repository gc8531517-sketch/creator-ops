(async function runOneExplicitExportJob() {
  "use strict";
  if (window.location.pathname !== '/creator-micro/content/manage') return;

  const params = new URLSearchParams(window.location.search);
  const jobId = params.get("codex_douyin_export_job");
  if (!jobId || !/^[A-Za-z0-9_-]{8,80}$/.test(jobId)) return;

  const startedAt = Date.now();
  const timeoutMs = 60_000;
  const intervalMs = 500;

  function publish(state, detail) {
    document.documentElement.dataset.codexDouyinExport = JSON.stringify({
      jobId,
      state,
      detail,
      at: new Date().toISOString()
    });
    console.info("[Douyin Export Bridge]", jobId, state, detail);
  }

  function attempt() {
    const result = globalThis.DouyinExportCore.findUniqueExportButton(
      document.querySelectorAll("button, [role='button']")
    );
    if (result.ok) {
      publish("clicked", "unique_export_button");
      result.button.click();
      return;
    }

    if (Date.now() - startedAt >= timeoutMs) {
      publish("failed", `export_button_count_${result.count}`);
      return;
    }
    window.setTimeout(attempt, intervalMs);
  }

  const claim = await chrome.runtime.sendMessage({ type: "claim_export_job", jobId });
  if (!claim?.ok) {
    publish("skipped", claim?.reason || "claim_failed");
    return;
  }

  publish("waiting", "looking_for_unique_export_button");
  attempt();
})();
