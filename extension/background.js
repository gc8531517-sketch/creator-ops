"use strict";

const claimedInThisWorker = new Set();

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type !== "claim_export_job") return false;

  try {
    const url = new URL(sender.url);
    if (url.origin !== 'https://creator.douyin.com' || url.pathname !== '/creator-micro/content/manage' || url.searchParams.get('codex_douyin_export_job') !== message.jobId) {
      sendResponse({ ok: false, reason: 'untrusted_sender' });
      return false;
    }
  } catch {
    sendResponse({ ok: false, reason: 'untrusted_sender' });
    return false;
  }

  const jobId = message.jobId;
  if (!/^[A-Za-z0-9_-]{8,80}$/.test(jobId || "")) {
    sendResponse({ ok: false, reason: "invalid_job_id" });
    return false;
  }

  const key = `exportJob:${jobId}`;
  if (claimedInThisWorker.has(jobId)) {
    sendResponse({ ok: false, reason: "already_claimed" });
    return false;
  }

  claimedInThisWorker.add(jobId);
  chrome.storage.local.get(key).then((stored) => {
    if (stored[key]) {
      sendResponse({ ok: false, reason: "already_claimed" });
      return;
    }

    return chrome.storage.local.set({
      [key]: {
        state: "claimed",
        claimedAt: new Date().toISOString()
      }
    }).then(() => sendResponse({ ok: true }));
  }).catch((error) => {
    claimedInThisWorker.delete(jobId);
    sendResponse({ ok: false, reason: String(error) });
  });

  return true;
});
