const assert = require("node:assert/strict");
const core = require("../../extension/export_core.js");

function element(text, { visible = true, disabled = false } = {}) {
  return {
    innerText: text,
    disabled,
    getClientRects() {
      return visible ? [{ width: 1, height: 1 }] : [];
    }
  };
}

assert.equal(core.normalizeText(" 导出  数据 \n"), "导出数据");

const unique = core.findUniqueExportButton([
  element("发布作品"),
  element("导出数据")
]);
assert.equal(unique.ok, true);
assert.equal(unique.count, 1);

const duplicate = core.findUniqueExportButton([
  element("导出数据"),
  element("导出数据")
]);
assert.equal(duplicate.ok, false);
assert.equal(duplicate.count, 2);

const hiddenIgnored = core.findUniqueExportButton([
  element("导出数据", { visible: false }),
  element("导出数据")
]);
assert.equal(hiddenIgnored.ok, true);
assert.equal(hiddenIgnored.count, 1);

const disabledIgnored = core.findUniqueExportButton([
  element("导出数据", { disabled: true })
]);
assert.equal(disabledIgnored.ok, false);
assert.equal(disabledIgnored.count, 0);

console.log("export_core tests passed");
