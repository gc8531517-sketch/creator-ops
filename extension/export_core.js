(function attachExportCore(root) {
  "use strict";

  function normalizeText(value) {
    return String(value || "").replace(/\s+/g, "").trim();
  }

  function isVisible(element) {
    if (!element || element.disabled) return false;
    if (typeof element.getClientRects === "function" && element.getClientRects().length === 0) {
      return false;
    }
    return true;
  }

  function findUniqueExportButton(elements) {
    const matches = Array.from(elements || []).filter((element) => {
      return isVisible(element) && normalizeText(element.innerText || element.textContent) === "导出数据";
    });
    return {
      ok: matches.length === 1,
      count: matches.length,
      button: matches.length === 1 ? matches[0] : null
    };
  }

  const api = { normalizeText, findUniqueExportButton };
  root.DouyinExportCore = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
