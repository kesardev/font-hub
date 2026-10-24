// Recycle UI test. Requires jsdom (npm i jsdom). Usage: BASE=http://127.0.0.1:13580 node ui_recycle_test.mjs
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { JSDOM, VirtualConsole } = require("jsdom");

const BASE = process.env.BASE || "http://127.0.0.1:13580";

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
  await waitFor(() => document.querySelectorAll("#fontRows tr").length >= 3, "font rows");
  const initialRows = document.querySelectorAll("#fontRows tr").length;

  document.querySelector("#settingsBtn").click();
  await waitFor(() => !document.querySelector("#settingsModal").hidden, "settings modal");
  await waitFor(() => document.querySelector("#recycleDays").value !== "", "retention field");
  assert.equal(Number(document.querySelector("#recycleDays").value), 30);
  document.querySelector("#recycleDays").value = "15";
  document.querySelector("#settingsSave").click();
  await waitFor(() => document.querySelector("#settingsHint").textContent.includes("已保存"), "settings saved");
  let project = await (await fetch(BASE + "/api/settings/project")).json();
  assert.equal(project.recycle_days, 15);
  await fetch(BASE + "/api/settings/project", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ recycle_days: 30 })
  });
  document.querySelector("#settingsClose").click();
  console.log("settings retention saves");

  const firstLink = document.querySelector("#fontRows .file-link");
  firstLink.click();
  await waitFor(() => document.querySelector('[data-delete-font]'), "delete button");
  document.querySelector("[data-delete-font]").click();
  await waitFor(() => !document.querySelector("#deleteModal").hidden, "delete modal");
  assert(!document.querySelector("#deletePermanent").checked);
  assert(document.querySelector("#deleteConfirm").textContent.includes("移入回收站"));
  document.querySelector("#deletePermanent").checked = true;
  document.querySelector("#deletePermanent").dispatchEvent(new window.Event("change", { bubbles: true }));
  assert(document.querySelector("#deleteConfirm").textContent.includes("永久删除"));
  document.querySelector("#deletePermanent").checked = false;
  document.querySelector("#deletePermanent").dispatchEvent(new window.Event("change", { bubbles: true }));
  document.querySelector("#deleteCancel").click();
  assert(document.querySelector("#deleteModal").hidden);
  console.log("delete confirmation and permanent checkbox work");

  document.querySelector("[data-delete-font]").click();
  await waitFor(() => !document.querySelector("#deleteModal").hidden, "delete modal reopen");
  document.querySelector("#deleteConfirm").click();
  await waitFor(() => document.querySelector("#deleteModal").hidden, "delete complete");
  await waitFor(() => document.querySelectorAll("#fontRows tr").length === initialRows - 1, "font removed");
  assert(document.querySelector("#drawer").hidden);

  document.querySelector("#recycleBtn").click();
  await waitFor(() => !document.querySelector("#recycleModal").hidden, "recycle modal");
  await waitFor(() => document.querySelectorAll("#recycleList .recycle-row").length === 1, "recycle item");
  assert(document.querySelector("#recycleList").textContent.includes("one.ttf") || document.querySelector("#recycleList").textContent.includes("two.ttf") || document.querySelector("#recycleList").textContent.includes("three.ttf"));
  console.log("deleted font appears in recycle bin");

  document.querySelector("[data-recycle-restore]").click();
  await waitFor(() => document.querySelectorAll("#fontRows tr").length === initialRows, "font restored");
  await waitFor(() => document.querySelector(".recycle-empty"), "recycle empty");
  console.log("recycle restore works");

  document.querySelector("#recycleClose").click();
  console.log("ALL RECYCLE UI CHECKS PASSED");
} finally {
  window.close();
}
