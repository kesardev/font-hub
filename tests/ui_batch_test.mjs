// Batch UI test. Requires jsdom. Usage: BASE=http://127.0.0.1:13581 node ui_batch_test.mjs
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { JSDOM, VirtualConsole } = require("jsdom");

const BASE = process.env.BASE || "http://127.0.0.1:13581";

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitFor(fn, label, timeout = 20000) {
  const started = Date.now();
  let lastError = null;
  while (Date.now() - started < timeout) {
    try {
      const value = await fn();
      if (value) return value;
    } catch (err) {
      lastError = err;
    }
    await sleep(100);
  }
  throw new Error("timeout waiting for " + label + (lastError ? ": " + lastError.message : ""));
}

const virtualConsole = new VirtualConsole();
virtualConsole.on("jsdomError", (err) => {
  if (!/Could not parse CSS stylesheet/.test(err.message)) console.error("jsdom:", err.message);
});

const dom = await JSDOM.fromURL(BASE + "/", {
  runScripts: "dangerously",
  resources: "usable",
  pretendToBeVisual: true,
  virtualConsole,
  beforeParse(window) {
    window.fetch = (input, init) => fetch(new URL(String(input), BASE + "/"), init);
    window.FontFace = class {
      constructor(family, source) { this.family = family; this.source = source; }
      load() { return Promise.resolve(this); }
    };
    Object.defineProperty(window.document, "fonts", {
      configurable: true,
      value: { add() {}, delete() { return true; }, has() { return false; } }
    });
    window.confirm = () => true;
  }
});

const { window } = dom;
const { document } = window;

try {
  await new Promise((resolve) => window.addEventListener("load", resolve));
  await waitFor(() => document.querySelectorAll("#fontRows tr").length === 3, "three rows");

  const rowChecks = () => Array.from(document.querySelectorAll("#fontRows .row-check"));
  assert.equal(rowChecks().length, 3);
  assert(document.querySelector("#batchBar").hidden);

  document.querySelector("#selectAll").click();
  assert(rowChecks().every((box) => box.checked));
  assert(!document.querySelector("#batchBar").hidden);
  assert.equal(document.querySelector("#selectedCount").textContent, "3");

  rowChecks()[0].click();
  assert.equal(document.querySelector("#selectedCount").textContent, "2");
  assert(document.querySelector("#selectAll").indeterminate);

  document.querySelector("#batchClear").click();
  assert(document.querySelector("#batchBar").hidden);
  assert(rowChecks().every((box) => !box.checked));
  console.log("select all / partial / clear work");

  rowChecks()[0].click();
  rowChecks()[1].click();
  assert.equal(document.querySelector("#selectedCount").textContent, "2");
  document.querySelector("#batchRecycle").click();
  await waitFor(() => !document.querySelector("#deleteModal").hidden, "batch recycle modal");
  assert(document.querySelector("#deleteTarget").textContent.includes("已选择 2 个字体"));
  assert(!document.querySelector("#deletePermanent").checked);
  document.querySelector("#deleteConfirm").click();
  await waitFor(() => document.querySelectorAll("#fontRows tr").length === 1, "two fonts recycled");
  assert(document.querySelector("#batchBar").hidden);

  document.querySelector("#recycleBtn").click();
  await waitFor(() => document.querySelectorAll("#recycleList .recycle-row").length === 2, "two recycle items");
  document.querySelector("[data-recycle-restore]").click();
  await waitFor(() => document.querySelectorAll("#fontRows tr").length === 2, "first restored");
  document.querySelector("[data-recycle-restore]").click();
  await waitFor(() => document.querySelectorAll("#fontRows tr").length === 3, "second restored");
  await waitFor(() => document.querySelector(".recycle-empty"), "recycle empty");
  document.querySelector("#recycleClose").click();
  console.log("batch recycle and restore work");

  rowChecks()[0].click();
  rowChecks()[1].click();
  document.querySelector("#batchDelete").click();
  await waitFor(() => !document.querySelector("#deleteModal").hidden, "batch delete modal");
  assert(document.querySelector("#deletePermanent").checked);
  assert(document.querySelector("#deleteConfirm").textContent.includes("永久删除 2 项"));
  document.querySelector("#deleteConfirm").click();
  await waitFor(() => document.querySelectorAll("#fontRows tr").length === 1, "two fonts permanently deleted");
  assert(document.querySelector("#batchBar").hidden);
  assert.equal((await (await fetch(BASE + "/api/recycle")).json()).total, 0);
  console.log("batch permanent delete works");

  console.log("ALL BATCH UI CHECKS PASSED");
} finally {
  window.close();
}
