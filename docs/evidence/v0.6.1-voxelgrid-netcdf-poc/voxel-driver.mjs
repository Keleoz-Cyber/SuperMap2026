// v0.6.1 VoxelGridLayer3D POC 驱动（Playwright Chromium）
// 用法：node voxel-driver.mjs <url> <outDir> [steps]
//   steps 逗号分隔：baseline,threshold,opacity,slice,contour（默认 baseline,threshold）
// 每个步骤输出一张截图 <step>.png；状态与请求记录进 <outDir>/run.json。
import { createRequire } from 'module';
import { writeFileSync, mkdirSync } from 'fs';

const require = createRequire('D:/Supermap/race_pro/web/package.json');
const { chromium } = require('@playwright/test');

const [url, outDir, stepsArg] = process.argv.slice(2);
const steps = (stepsArg || 'baseline,threshold').split(',');
mkdirSync(outDir, { recursive: true });

const browser = await chromium.launch({ headless: true, args: ['--enable-unsafe-swiftshader'] });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

const console_ = [];
page.on('console', (m) => console_.push({ type: m.type(), text: m.text().slice(0, 400) }));
page.on('pageerror', (e) => console_.push({ type: 'pageerror', text: String(e).slice(0, 400) }));
page.on('requestfailed', (r) => console_.push({ type: 'requestfailed', text: `${r.url()} ${r.failure()?.errorText}` }));
const badResponses = [];
page.on('response', (r) => { if (r.status() >= 400) badResponses.push(`${r.status()} ${r.url().slice(0, 200)}`); });
const sdkRequests = [];
page.on('request', (r) => {
  const u = r.url();
  if (u.includes('.nc') || u.includes('SuperMap3D-2026') || u.includes('Workers')) sdkRequests.push(u.slice(0, 220));
});

await page.goto(url, { waitUntil: 'load', timeout: 60000 });

let finalPhase = 'timeout';
try {
  await page.waitForFunction(
    () => window.__VOXEL_POC__ && ['rendered', 'failed'].includes(window.__VOXEL_POC__.phase),
    undefined, { timeout: 90000 });
  finalPhase = await page.evaluate(() => window.__VOXEL_POC__.phase);
} catch { /* 保留 timeout */ }

const pocState = await page.evaluate(() => JSON.parse(JSON.stringify(window.__VOXEL_POC__ || {})));
const layerDump = await page.evaluate(() => {
  const l = window.__layer;
  if (!l) return null;
  const pick = {};
  for (const k of ['type', 'visible', '_startRender', 'minFiltration', 'maxFiltration', 'minValue', 'maxValue',
    'volumeRenderMode', 'opaqueRate', 'useGradientOpacity', 'gradientOpacityMinOpacity', 'gradientOpacityMaxOpacity',
    'gradientOpacityMinValue', 'gradientOpacityMaxValue', 'fillStyle', 'enableLighting', 'scale', 'contourValue']) {
    try { pick[k] = l[k]; } catch (e) { pick[k] = 'err'; }
  }
  try { pick.frameStateMode = l._frameState ? l._frameState.mode : null; } catch (e) { pick.frameStateMode = 'err'; }
  try { pick.zBounds = l._zBounds ? [l._zBounds.x, l._zBounds.y] : null; } catch (e) { pick.zBounds = 'err'; }
  const t = l._voxelGridTile;
  pick.hasVoxelGridTile = !!t;
  if (t) {
    for (const k of ['_floor', '_ceil', '_nWidth', '_nHeight', '_nDepth', '_nSideBlockCount', '_nBlockLength', '_nLength', '_isVisible']) {
      try { pick['tile' + k] = t[k]; } catch (e) { pick['tile' + k] = 'err'; }
    }
    try { pick.tileVolTextures = t._volTextures ? t._volTextures.length : null; } catch (e) { pick.tileVolTextures = 'err'; }
    try { pick.tileOutputKeys = t.output ? Object.keys(t.output) : null; } catch (e) { pick.tileOutputKeys = 'err'; }
    try { pick.tileOutputDims = t.output ? [t.output.xDimSize, t.output.yDimSize, t.output.zDimSize, t.output.minValue, t.output.maxValue] : null; } catch (e) { pick.tileOutputDims = 'err'; }
    try { pick.tileBoundingSphere = t._boundingSphere ? [t._boundingSphere.center, t._boundingSphere.radius] : null; } catch (e) { pick.tileBoundingSphere = 'err'; }
    try { pick.tileHasVolumeBoxCommand = !!t._volumeBoxCommand; } catch (e) { pick.tileHasVolumeBoxCommand = 'err'; }
    try {
      const c = t._volumeBoxCommand;
      pick.cmdBoundingVolume = c && c.boundingVolume ? [c.boundingVolume.center, c.boundingVolume.radius] : null;
      pick.cmdPrimitiveType = c ? c.primitiveType : null;
      pick.cmdCount = c ? c.count : null;
      pick.cmdCull = c ? c.cull : null;
      pick.cmdShow = c ? c.show : null;
      pick.cmdPass = c ? c.pass : null;
      pick.cmdHasShaderProgram = c ? !!c.shaderProgram : null;
    } catch (e) { pick.cmdError = String(e); }
    try {
      const gl = window.__scene && window.__scene._context && window.__scene._context._gl;
      pick.glError = gl ? gl.getError() : 'no-gl-handle';
      pick.glLost = gl ? gl.isContextLost() : null;
    } catch (e) { pick.glError = 'err:' + e; }
    try { pick.tileHasOutlineCommand = !!t._outlineCommand; } catch (e) { pick.tileHasOutlineCommand = 'err'; }
    try { pick.tileHasContourCommand = !!t._contourCommand; } catch (e) { pick.tileHasContourCommand = 'err'; }
  }
  try { pick.camera = window.__scene ? window.__scene.camera.position : null; } catch (e) { pick.camera = 'err'; }
  return pick;
});
const gpu = await page.evaluate(() => {
  try {
    const gl = document.createElement('canvas').getContext('webgl2');
    const ext = gl && gl.getExtension('WEBGL_debug_renderer_info');
    return { webgl2: !!gl, renderer: ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : 'n/a', ua: navigator.userAgent, dpr: window.devicePixelRatio };
  } catch (e) { return { error: String(e) }; }
});

// 中央有效区（避开左上 46% 面板）：右半区中央；FULLSHOT=1 时全帧
const clip = process.env.FULLSHOT === '1' ? undefined : { x: 740, y: 120, width: 640, height: 640 };

async function shot(name) {
  await page.screenshot({ path: `${outDir}/${name}.png`, clip });
}

async function applyStep(name) {
  if (name === 'baseline') return;
  if (name === 'threshold') {
    await page.evaluate(() => {
      const l = window.__layer;
      const [a, b] = [l.minFiltration, l.maxFiltration];
      const mid = a + (b - a) * 0.55;
      l.minFiltration = mid;
      document.getElementById('ctl-min').value = String(mid);
      window.__VOXEL_POC__.thresholds = { min: l.minFiltration, max: l.maxFiltration };
    });
  } else if (name === 'opacity') {
    await page.evaluate(() => {
      const l = window.__layer;
      const o = new SuperMap3D.PiecewiseFunction();
      o.addPoint(l.minFiltration, 0.12);
      o.addPoint(l.maxFiltration, 0.12);
      l.opacityTransferFunction = o;
    });
  } else if (name === 'opacity-nodirty') {
    await page.evaluate(() => { window.__layer.opaqueRate = 0.3; });
  } else if (name === 'slice' || name === 'contour') {
    await page.evaluate((m) => {
      const modeName = m === 'slice' ? 'Slice' : 'ContourValue';
      window.__layer.volumeRenderMode = SuperMap3D.VolumeRenderMode[modeName];
      window.__VOXEL_POC__.renderMode = modeName;
    }, name);
  } else if (name === 'nograd') {
    await page.evaluate(() => { window.__layer.useGradientOpacity = false; });
  } else if (name === 'nolight') {
    await page.evaluate(() => { window.__layer.enableLighting = false; });
  } else if (name.startsWith('passto:')) {
    const pass = Number(name.split(':')[1]);
    await page.evaluate((p) => {
      const t = window.__layer._voxelGridTile;
      if (t._volumeBoxCommand) t._volumeBoxCommand.pass = p;
      if (t._outlineCommand) t._outlineCommand.pass = p;
    }, pass);
  }
  // 参数生效等待：连续 animation frame（非固定长延时），上限 90 帧
  await page.evaluate(() => new Promise((resolve) => {
    let n = 0;
    const tick = () => { n += 1; n >= 45 ? resolve() : requestAnimationFrame(tick); };
    requestAnimationFrame(tick);
  }));
}

for (const step of steps) {
  await applyStep(step);
  await shot(step);
}

// 执行探针：挂钩 volumeBoxCommand.execute 与 tile.update，统计 60 帧内的真实调用次数
// （execute 挂钩跟随命令对象重建安装；同时记录 commandList 长度变化）
const execProbe = await page.evaluate(() => new Promise((resolve) => {
  try {
    const t = window.__layer && window.__layer._voxelGridTile;
    if (!t) { resolve({ ok: false, reason: 'no tile' }); return; }
    const counts = { tileUpdate: 0, pushes: 0, volumeBoxExecute: 0, recreated: 0 };
    let lastCmd = t._volumeBoxCommand || null;
    const hookCmd = (c) => {
      if (!c || c.__hooked) return;
      c.__hooked = true;
      const orig = c.execute;
      c.execute = function (...args) { counts.volumeBoxExecute += 1; return orig.apply(this, args); };
    };
    hookCmd(lastCmd);
    const origUpdate = t.update;
    t.update = function (r, n) {
      counts.tileUpdate += 1;
      const before = n && n.commandList ? n.commandList.length : -1;
      const ret = origUpdate.apply(this, arguments);
      const after = n && n.commandList ? n.commandList.length : -1;
      if (after > before) counts.pushes += after - before;
      try {
        counts.passesRender = n.passes ? !!n.passes.render : null;
        counts.passesPick = n.passes ? !!n.passes.pick : null;
        counts.cmdInList = n.commandList ? n.commandList.includes(this._volumeBoxCommand) : null;
        counts.listLength = after;
      } catch (e) { /* 忽略 */ }
      if (this._volumeBoxCommand && this._volumeBoxCommand !== lastCmd) {
        counts.recreated += 1;
        lastCmd = this._volumeBoxCommand;
        hookCmd(lastCmd);
      }
      return ret;
    };
    let frames = 0;
    const tick = () => {
      frames += 1;
      if (frames >= 60) resolve({ ok: true, frames, ...counts });
      else requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  } catch (e) { resolve({ ok: false, reason: String(e) }); }
}));
const run = { url, finalPhase, pocState, layerDump, execProbe, gpu, badResponses, sdkRequests, console: console_ };
writeFileSync(`${outDir}/run.json`, JSON.stringify(run, null, 2));
console.log(JSON.stringify({ finalPhase, layerType: pocState.layerType, renderMode: pocState.renderMode, errors: pocState.errors, badResponses, layerDump, ncRequests: sdkRequests.filter((u) => u.includes('.nc')) }, null, 2));
await browser.close();
process.exit(finalPhase === 'rendered' ? 0 : 2);
