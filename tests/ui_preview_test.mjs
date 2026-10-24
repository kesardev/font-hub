// Preview UI test. Requires jsdom (npm i jsdom). Usage: BASE=http://127.0.0.1:13579 node ui_preview_test.mjs
import assert from "node:assert/strict";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { JSDOM, VirtualConsole } = require("jsdom");

const BASE = process.env.BASE || "http://127.0.0.1:13579";
const fontFaceLog = { added: 0, deleted: 0 };

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
virtualConsole.on("error", (...args) => console.error("console.error:", ...args));

const dom = await JSDOM.fromURL(BASE + "/", {
  runScripts: "dangerously",
  resources: "usable",
  pretendToBeVisual: true,
  virtualConsole,
  beforeParse(window) {
    window.fetch = (input, init) => fetch(new URL(String(input), BASE + "/"), init);
    window.FontFace = class {
      constructor(family, source) {
        this.family = family;
        this.source = source;
        this.status = "unloaded";
      }
      load() {
        this.status = "loaded";
        return Promise.resolve(this);
      }
    };
    Object.defineProperty(window.document, "fonts", {
      configurable: true,
      value: {
        add() { fontFaceLog.added += 1; },
        delete() { fontFaceLog.deleted += 1; return true; },
        has() { return false; }
      }
    });
    window.confirm = () => true;
  }
});

const { window } = dom;
const { document } = window;

try {
  await new Promise((resolve) => window.addEventListener("load", resolve));
  await waitFor(() => document.querySelectorAll("#fontRows tr").length > 0, "font rows");
  console.log("page loaded:", document.querySelectorAll("#fontRows tr").length, "rows");

  const fontList = await (await fetch(BASE + "/api/fonts?page_size=500")).json();
  const ttc = fontList.items.find((item) => item.ext === ".ttc" && item.parse_status === "ok");
  const ttf = fontList.items.find((item) => item.ext === ".ttf" && item.parse_status === "ok");
  assert(ttc && ttc.face_count > 2, "need a multi-face TTC");
  assert(ttf, "need a working TTF");

  const ttcLink = document.querySelector('.file-link[data-id="' + ttc.id + '"]');
  assert(ttcLink, "TTC row link missing");
  ttcLink.click();
  await waitFor(() => document.querySelectorAll("#previewBlocks .preview-block").length === 4, "four preview blocks");

  const blocks = Array.from(document.querySelectorAll("#previewBlocks .preview-block"));
  assert.deepEqual(
    blocks.map((block) => block.dataset.key),
    ["preview_cn", "preview_en", "preview_punct", "preview_special"]
  );
  assert.deepEqual(
    blocks.map((block) => block.querySelector(".preview-label span:first-child").textContent),
    ["中文", "英文", "标点（中/英/数字）", "特殊"]
  );
  console.log("four groups rendered separately");

  const cn = document.querySelector('.preview-block[data-key="preview_cn"]');
  assert(!cn.querySelector(".preview-text").classList.contains("has-missing"));
  assert.match(cn.querySelector(".preview-label span:last-child").textContent, /字形完整/);
  assert(cn.textContent.includes("天地玄黄"));
  assert(cn.textContent.includes("黃"));
  assert.equal(cn.querySelectorAll(".preview-line").length, 2);
  const en = document.querySelector('.preview-block[data-key="preview_en"]');
  assert.equal(en.querySelectorAll(".preview-line").length, 2);
  assert(en.textContent.includes("THE QUICK"));
  assert(en.textContent.includes("the quick"));
  const punct = document.querySelector('.preview-block[data-key="preview_punct"]');
  assert.equal(punct.querySelectorAll(".preview-line").length, 3);
  assert(punct.textContent.includes("0123456789"));
  console.log("default cn/en/punct line groups complete");

  const faceSelect = document.querySelector("#previewFace");
  assert(faceSelect, "TTC face selector missing");
  assert.equal(faceSelect.options.length, ttc.face_count);
  faceSelect.value = "2";
  faceSelect.dispatchEvent(new window.Event("change", { bubbles: true }));
  await waitFor(() => window.state && window.state.previewFaceIndex === 2, "face switch");
  await waitFor(
    () => document.querySelector('.preview-block[data-key="preview_special"] .preview-label span:last-child').textContent.includes("缺字"),
    "missing glyph report"
  );
  const special = document.querySelector('.preview-block[data-key="preview_special"]');
  assert(special.querySelector(".preview-text").classList.contains("has-missing"));
  assert(special.querySelector(".missing-glyph"), "missing glyph span missing");
  assert.match(special.querySelector(".preview-label span:last-child").textContent, /缺字 1 种/);
  console.log("missing glyph highlighted on TTC face 2");

  const range = document.querySelector("#previewSize");
  range.value = "40";
  range.dispatchEvent(new window.Event("input", { bubbles: true }));
  assert.equal(document.querySelector("#previewBlocks [data-preview-text]").style.fontSize, "40px");
  console.log("preview size slider applies");

  const originalFetch = window.fetch;
  const cnText = window.state.previewTexts.preview_cn;
  const enText = window.state.previewTexts.preview_en;
  const punctText = window.state.previewTexts.preview_punct;
  const specialText = window.state.previewTexts.preview_special;
  const cnLines = cnText.split("\n");
  assert.equal(cnLines.length, 2);
  const simpSet = new Set(Array.from(cnLines[0]));
  const tradSet = new Set(Array.from(cnLines[1]));
  const tradOnly = Array.from(new Set(Array.from(cnLines[1]))).filter((ch) => !simpSet.has(ch) && !/\s/.test(ch));
  const simpOnly = Array.from(new Set(Array.from(cnLines[0]))).filter((ch) => !tradSet.has(ch) && !/\s/.test(ch));
  assert(tradOnly.length >= 3 && simpOnly.length >= 3);

  function uniqueChars(text) {
    return Array.from(new Set(Array.from(text))).filter((ch) => !/\s/.test(ch));
  }

  function resultFor(text, missingChars) {
    const missing = missingChars.map((ch) => ({
      char: ch,
      codepoint: "U+" + ch.codePointAt(0).toString(16).toUpperCase().padStart(4, "0")
    }));
    const total = Array.from(text).filter((ch) => !/\s/.test(ch)).length;
    return {
      total: total,
      missing_count: missing.length,
      missing_occurrences: missing.length,
      missing: missing,
      coverage: total ? (total - missing.length) / total : 1
    };
  }

  const complete = { total: 1, missing_count: 0, missing_occurrences: 0, missing: [], coverage: 1 };

  function fakeCoverage(overrides) {
    const results = {
      preview_cn: complete,
      preview_en: complete,
      preview_punct: complete,
      preview_special: complete
    };
    Object.keys(overrides).forEach((key) => { results[key] = overrides[key]; });
    return { face: window.state.previewFaceIndex, no_cmap: false, results: results };
  }

  function stubCoverage(overrides) {
    const payload = fakeCoverage(overrides);
    window.fetch = function (input, init) {
      if (String(input).includes("/coverage")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: function () { return Promise.resolve(payload); },
          text: function () { return Promise.resolve(JSON.stringify(payload)); }
        });
      }
      return originalFetch(input, init);
    };
  }

  function labelOf(key) {
    return document.querySelector('.preview-block[data-key="' + key + '"] .preview-label span:first-child').textContent;
  }

  stubCoverage({ preview_cn: resultFor(cnText, [tradOnly[0]]) });
  await window.refreshPreviewCoverage();
  await waitFor(() => labelOf("preview_cn") === "中文", "mixed chinese label");
  let cnBlock = document.querySelector('.preview-block[data-key="preview_cn"]');
  assert.equal(cnBlock.querySelectorAll(".preview-line").length, 2);
  assert(cnBlock.querySelector(".missing-glyph"));
  assert(!cnBlock.querySelector(".preview-note"));
  console.log("one missing traditional glyph keeps both lines");

  stubCoverage({ preview_cn: resultFor(cnText, tradOnly) });
  await window.refreshPreviewCoverage();
  await waitFor(() => labelOf("preview_cn").includes("仅简体"), "simplified-only collapse");
  cnBlock = document.querySelector('.preview-block[data-key="preview_cn"]');
  assert.equal(cnBlock.querySelectorAll(".preview-line").length, 1);
  assert(!cnBlock.querySelector(".preview-text").classList.contains("has-missing"));
  assert(cnBlock.textContent.includes("已只显示简体行"));
  const cnToggle = cnBlock.querySelector(".preview-toggle");
  assert(cnToggle && cnToggle.textContent.includes("展开全部行"));
  cnToggle.click();
  await waitFor(() => document.querySelector('.preview-block[data-key="preview_cn"]').querySelectorAll(".preview-line").length === 2, "expand chinese");
  cnBlock = document.querySelector('.preview-block[data-key="preview_cn"]');
  assert.equal(labelOf("preview_cn"), "中文");
  assert(cnBlock.querySelector(".missing-glyph"));
  assert(!cnBlock.querySelector(".preview-note"));
  assert(cnBlock.querySelector(".preview-toggle").textContent.includes("收起为单列"));
  cnBlock.querySelector(".preview-toggle").click();
  await waitFor(() => document.querySelector('.preview-block[data-key="preview_cn"]').querySelectorAll(".preview-line").length === 1, "collapse chinese");
  assert(labelOf("preview_cn").includes("仅简体"));
  console.log("chinese toggle expands to two lines and restores one line");

  stubCoverage({ preview_cn: resultFor(cnText, simpOnly) });
  await window.refreshPreviewCoverage();
  await waitFor(() => labelOf("preview_cn").includes("仅繁体"), "traditional-only collapse");
  cnBlock = document.querySelector('.preview-block[data-key="preview_cn"]');
  assert.equal(cnBlock.querySelectorAll(".preview-line").length, 1);
  assert(!cnBlock.querySelector(".preview-text").classList.contains("has-missing"));
  assert(cnBlock.textContent.includes("已只显示繁体行"));
  console.log("traditional-only font collapses to one line");

  const enLines = enText.split("\n");
  assert.equal(enLines.length, 2);
  const upperChars = uniqueChars(enLines[0]);
  const lowerChars = uniqueChars(enLines[1]);

  stubCoverage({ preview_en: resultFor(enText, lowerChars) });
  await window.refreshPreviewCoverage();
  await waitFor(() => labelOf("preview_en").includes("仅大写"), "uppercase-only collapse");
  let enBlock = document.querySelector('.preview-block[data-key="preview_en"]');
  assert.equal(enBlock.querySelectorAll(".preview-line").length, 1);
  assert(!enBlock.querySelector(".preview-text").classList.contains("has-missing"));
  assert(enBlock.textContent.includes("已只显示大写行"));
  console.log("uppercase-only font collapses to one line");

  stubCoverage({ preview_en: resultFor(enText, upperChars) });
  await window.refreshPreviewCoverage();
  await waitFor(() => labelOf("preview_en").includes("仅小写"), "lowercase-only collapse");
  enBlock = document.querySelector('.preview-block[data-key="preview_en"]');
  assert.equal(enBlock.querySelectorAll(".preview-line").length, 1);
  assert(!enBlock.querySelector(".preview-text").classList.contains("has-missing"));
  assert(enBlock.textContent.includes("已只显示小写行"));
  console.log("lowercase-only font collapses to one line");

  stubCoverage({});
  window.state.previewCaseStyle = "upper";
  await window.refreshPreviewCoverage();
  await waitFor(() => labelOf("preview_en").includes("仅大写"), "case-style upper");
  enBlock = document.querySelector('.preview-block[data-key="preview_en"]');
  assert.equal(enBlock.querySelectorAll(".preview-line").length, 1);
  assert(!enBlock.querySelector(".missing-glyph"));
  assert(enBlock.textContent.includes("使用大写设计"));
  const enToggle = enBlock.querySelector(".preview-toggle");
  assert(enToggle && enToggle.textContent.includes("展开全部行"));
  enToggle.click();
  await waitFor(() => document.querySelector('.preview-block[data-key="preview_en"]').querySelectorAll(".preview-line").length === 2, "expand english");
  enBlock = document.querySelector('.preview-block[data-key="preview_en"]');
  assert.equal(labelOf("preview_en"), "英文");
  assert(enBlock.querySelector(".preview-toggle").textContent.includes("收起为单列"));
  enBlock.querySelector(".preview-toggle").click();
  await waitFor(() => document.querySelector('.preview-block[data-key="preview_en"]').querySelectorAll(".preview-line").length === 1, "collapse english");
  assert(labelOf("preview_en").includes("仅大写"));
  console.log("caps-only mapped font expands and collapses via toggle");

  window.state.previewCaseStyle = "upper-only";
  await window.refreshPreviewCoverage();
  await waitFor(() => labelOf("preview_en").includes("仅大写"), "case-style upper-only");
  enBlock = document.querySelector('.preview-block[data-key="preview_en"]');
  assert.equal(enBlock.querySelectorAll(".preview-line").length, 1);
  assert(enBlock.textContent.includes("缺少小写字形"));

  window.state.previewCaseStyle = "lower-only";
  await window.refreshPreviewCoverage();
  await waitFor(() => labelOf("preview_en").includes("仅小写"), "case-style lower-only");
  enBlock = document.querySelector('.preview-block[data-key="preview_en"]');
  assert.equal(enBlock.querySelectorAll(".preview-line").length, 1);
  assert(enBlock.textContent.includes("缺少大写字形"));
  console.log("upper-only and lower-only case styles collapse");

  window.state.previewCaseStyle = "lower";
  await window.refreshPreviewCoverage();
  await waitFor(() => labelOf("preview_en").includes("仅小写"), "case-style lower");
  enBlock = document.querySelector('.preview-block[data-key="preview_en"]');
  assert.equal(enBlock.querySelectorAll(".preview-line").length, 1);
  assert(enBlock.textContent.includes("使用小写设计"));
  console.log("lowercase-designed font collapses via case-style");

  window.state.previewCaseStyle = "unicase";
  await window.refreshPreviewCoverage();
  await waitFor(() => labelOf("preview_en").includes("大小写同形"), "case-style unicase");
  enBlock = document.querySelector('.preview-block[data-key="preview_en"]');
  assert.equal(enBlock.querySelectorAll(".preview-line").length, 1);
  assert(enBlock.textContent.includes("外观相同"));
  console.log("unicase font collapses to one line");

  window.state.previewCaseStyle = "mixed";
  await window.refreshPreviewCoverage();
  await waitFor(() => labelOf("preview_en") === "英文", "case-style mixed");
  assert.equal(document.querySelector('.preview-block[data-key="preview_en"]').querySelectorAll(".preview-line").length, 2);

  const punctLines = punctText.split("\n");
  assert.equal(punctLines.length, 3);
  const cnPunctChars = uniqueChars(punctLines[0]);
  const enPunctChars = uniqueChars(punctLines[1]);
  const digitChars = uniqueChars(punctLines[2]);

  stubCoverage({ preview_punct: resultFor(punctText, cnPunctChars) });
  await window.refreshPreviewCoverage();
  await waitFor(() => labelOf("preview_punct").includes("英/数字"), "chinese punctuation hidden");
  let punctBlock = document.querySelector('.preview-block[data-key="preview_punct"]');
  assert.equal(punctBlock.querySelectorAll(".preview-line").length, 2);
  assert(!punctBlock.querySelector(".preview-text").classList.contains("has-missing"));
  assert(punctBlock.textContent.includes("中文标点"));
  console.log("missing Chinese punctuation hides that line");

  stubCoverage({ preview_punct: resultFor(punctText, digitChars) });
  await window.refreshPreviewCoverage();
  await waitFor(() => labelOf("preview_punct").includes("中/英"), "digits hidden");
  punctBlock = document.querySelector('.preview-block[data-key="preview_punct"]');
  assert.equal(punctBlock.querySelectorAll(".preview-line").length, 2);
  assert(!punctBlock.querySelector(".preview-text").classList.contains("has-missing"));
  assert(punctBlock.textContent.includes("数字"));
  console.log("missing digits hides the digit line");

  stubCoverage({ preview_punct: resultFor(punctText, cnPunctChars.concat(enPunctChars)) });
  await window.refreshPreviewCoverage();
  await waitFor(() => labelOf("preview_punct").includes("仅数字"), "punctuation digits only");
  punctBlock = document.querySelector('.preview-block[data-key="preview_punct"]');
  assert.equal(punctBlock.querySelectorAll(".preview-line").length, 1);
  assert(!punctBlock.querySelector(".preview-text").classList.contains("has-missing"));
  assert(punctBlock.textContent.includes("中文标点") && punctBlock.textContent.includes("英文标点"));
  const punctToggle = punctBlock.querySelector(".preview-toggle");
  assert(punctToggle && punctToggle.textContent.includes("展开全部行"));
  punctToggle.click();
  await waitFor(() => document.querySelector('.preview-block[data-key="preview_punct"]').querySelectorAll(".preview-line").length === 3, "expand punctuation");
  punctBlock = document.querySelector('.preview-block[data-key="preview_punct"]');
  assert.equal(labelOf("preview_punct"), "标点（中/英/数字）");
  assert(punctBlock.querySelector(".missing-glyph"));
  assert(punctBlock.querySelector(".preview-toggle").textContent.includes("收起为单列"));
  punctBlock.querySelector(".preview-toggle").click();
  await waitFor(() => document.querySelector('.preview-block[data-key="preview_punct"]').querySelectorAll(".preview-line").length === 1, "collapse punctuation");
  assert(labelOf("preview_punct").includes("仅数字"));
  console.log("punctuation toggle expands to three lines and restores one line");

  const specialChars = uniqueChars(specialText);
  stubCoverage({ preview_special: resultFor(specialText, specialChars) });
  await window.refreshPreviewCoverage();
  await waitFor(() => labelOf("preview_special") === "特殊", "special label");
  const specialBlock = document.querySelector('.preview-block[data-key="preview_special"]');
  assert.equal(specialBlock.querySelectorAll(".preview-line").length, 1);
  assert(specialBlock.querySelector(".preview-text").classList.contains("has-missing"));
  assert(!specialBlock.querySelector(".preview-note"));
  assert(!specialBlock.querySelector(".preview-toggle"));
  console.log("special symbols only highlight, never collapse or toggle");

  window.fetch = originalFetch;
  await window.refreshPreviewCoverage();
  await waitFor(
    () => labelOf("preview_cn") === "中文" && labelOf("preview_en") === "英文" && labelOf("preview_punct") === "标点（中/英/数字）",
    "restore labels"
  );
  assert.equal(document.querySelector('.preview-block[data-key="preview_cn"]').querySelectorAll(".preview-line").length, 2);
  assert.equal(document.querySelector('.preview-block[data-key="preview_en"]').querySelectorAll(".preview-line").length, 2);
  assert.equal(document.querySelector('.preview-block[data-key="preview_punct"]').querySelectorAll(".preview-line").length, 3);
  assert.equal(document.querySelector('.preview-block[data-key="preview_special"]').querySelectorAll(".preview-line").length, 1);

  const custom = document.querySelector("#previewCustom");
  assert(custom, "custom preview textarea missing");
  custom.value = "A\u{10FFFD}\u{10FFFD}";
  custom.dispatchEvent(new window.Event("input", { bubbles: true }));
  assert(document.querySelector('.preview-block[data-key="custom"]'), "custom block should render immediately");
  await waitFor(() => {
    const block = document.querySelector('.preview-block[data-key="custom"]');
    return block && block.querySelector(".preview-label span:last-child").textContent.includes("缺字 1 种");
  }, "custom coverage");
  const customBlock = document.querySelector('.preview-block[data-key="custom"]');
  assert.equal(customBlock.querySelectorAll(".missing-glyph").length, 2);
  assert.match(customBlock.querySelector(".preview-label span:last-child").textContent, /33\.3%/);
  console.log("custom text renders with per-character missing highlight");

  document.querySelector("#settingsBtn").click();
  await waitFor(() => !document.querySelector("#settingsModal").hidden, "settings modal");
  await waitFor(() => document.querySelector("#preview_punct").placeholder.includes("0123456789"), "settings placeholders");
  assert(document.querySelector("#preview_special").placeholder.includes("✗"));
  document.querySelector("#settingsClose").click();

  document.querySelector("#drawerClose").click();
  assert(document.querySelector("#drawer").hidden);
  assert.equal(window.state.previewData, null);
  assert.equal(window.state.previewFontFace, null);
  assert(fontFaceLog.deleted >= 1, "FontFace should be deleted on close");
  console.log("drawer close clears preview state and font face");

  document.querySelector('.file-link[data-id="' + ttf.id + '"]').click();
  await waitFor(() => document.querySelectorAll("#previewBlocks .preview-block").length === 4, "TTF preview");
  assert.equal(window.state.previewData.id, ttf.id);
  assert(!document.querySelector("#previewError").textContent);
  document.querySelector("#drawerClose").click();
  console.log("reopen TTF preview cleanly");

  console.log("ALL UI CHECKS PASSED");
} finally {
  window.close();
}
