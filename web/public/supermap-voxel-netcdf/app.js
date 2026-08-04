/* v0.6.1 VoxelGridLayer3D + NetCDF POC（独立页，仅全局 SuperMap3D，不混旧 Cesium）
 *
 * 两种数据源：
 *   ?source=probe           阶段 A：静态 4x5x6 非对称探针（不接 API）
 *   默认（?result_id=...）  阶段 C：API manifest + volume.nc（身份断言后加载）
 * 测试模式 ?clean=1：关闭天空/底图/大气，便于像素归因。
 */
'use strict';

const POC = {
  phase: 'ready',
  identity: { resultId: null, gridSha256: null, netcdfSha256: null },
  layerType: null,
  renderMode: null,
  thresholds: { min: null, max: null },
  errors: [],
};
window.__VOXEL_POC__ = POC;

const statusEl = document.getElementById('status');
const diag = { sdk: null, contextType: 2, ncUrl: null, notes: [] };

function renderStatus() {
  const s = POC;
  statusEl.textContent = [
    `SDK version: ${diag.sdk ?? 'n/a'}`,
    `WebGL/WebGPU context type: ${diag.contextType} (2=WebGL2)`,
    `phase: ${s.phase}`,
    `result_id: ${s.identity.resultId ?? 'n/a'}`,
    `grid_sha256: ${s.identity.gridSha256 ?? 'n/a'}`,
    `NetCDF URL: ${diag.ncUrl ?? 'n/a'}`,
    `NetCDF SHA-256: ${s.identity.netcdfSha256 ?? 'n/a'}`,
    `layer constructor/type: ${s.layerType ?? 'n/a'}`,
    `current render mode: ${s.renderMode ?? 'n/a'}`,
    `current thresholds: [${s.thresholds.min}, ${s.thresholds.max}]`,
    `errors: ${s.errors.length ? JSON.stringify(s.errors) : 'none'}`,
    ...diag.notes.map((n) => `note: ${n}`),
  ].join('\n');
}

function pushError(code, message) {
  POC.errors.push({ code, message: String(message).slice(0, 500) });
  POC.phase = 'failed';
  renderStatus();
}
window.addEventListener('error', (e) => pushError('PAGE_ERROR', e.message || e.type));
window.addEventListener('unhandledrejection', (e) =>
  pushError('UNHANDLED_REJECTION', (e.reason && (e.reason.message || e.reason.stack)) || e.reason));

const query = new URLSearchParams(location.search);

function checkResponse(r, what) {
  if (!r.ok) throw new Error(`${what} HTTP ${r.status}`);
  const type = (r.headers.get('content-type') || '').toLowerCase();
  if (type.includes('text/html')) throw new Error(`${what} 返回 HTML 错误页`);
  return r;
}

/* 有上限的渲染稳定等待：无新增网络请求 + 连续 N 个 animation frame（非固定延时） */
function waitRenderSettled(maxFrames = 900, stableFrames = 12) {
  return new Promise((resolve) => {
    let frames = 0;
    let stable = 0;
    let lastResources = -1;
    const tick = () => {
      frames += 1;
      const count = performance.getEntriesByType('resource').length;
      if (count === lastResources) stable += 1;
      else { stable = 0; lastResources = count; }
      if ((stable >= stableFrames && frames > 30) || frames >= maxFrames) resolve();
      else requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });
}

/* startRender 内部 _initialize 读取 frameState.mode；图层的 _frameState 由渲染循环
 * 在下一帧 update() 赋值。有上限轮询该渲染后状态（非固定延时）。 */
function waitLayerFrameState(layer, maxFrames = 600) {
  return new Promise((resolve, reject) => {
    let frames = 0;
    const tick = () => {
      frames += 1;
      if (layer._frameState) { resolve(frames); return; }
      if (frames >= maxFrames) { reject(new Error('VOXEL_LAYER_LOAD_FAILED: 600 帧内 _frameState 未就绪')); return; }
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });
}

async function loadConfig() {
  if (query.get('source') === 'probe') {
    return {
      variableName: 'rho',
      dimensionNames: ['x', 'y', 'z'],
      ncUrl: './probe/probe-4x5x6.nc',
      boundsDeg: { west: 119.9997, south: 29.9997, east: 120.0003, north: 30.0003 },
      zBounds: [-810, -90],
      valueRange: [10, 610],
      identity: { resultId: 'phase-a-probe', gridSha256: 'n/a', netcdfSha256: 'n/a' },
    };
  }
  const resultId = query.get('result_id');
  if (!resultId) throw new Error('缺少 ?result_id= 或 ?source=probe');
  const expectedGrid = query.get('grid_sha256');
  const exportRes = await fetch(`/api/results/${encodeURIComponent(resultId)}/supermap-voxel-netcdf-export`)
    .then((r) => checkResponse(r, 'export')).then((r) => r.json());
  const exportId = exportRes.export_id;
  const manifest = await fetch(`/api/supermap-voxel-netcdf-exports/${encodeURIComponent(exportId)}/manifest`)
    .then((r) => checkResponse(r, 'manifest')).then((r) => r.json());
  if (manifest.candidate_result_id !== resultId) throw new Error(`VOXEL_NC_IDENTITY_MISMATCH result_id ${manifest.candidate_result_id}`);
  if (expectedGrid && manifest.grid_sha256 !== expectedGrid) throw new Error(`VOXEL_NC_IDENTITY_MISMATCH grid_sha256 ${manifest.grid_sha256}`);
  return {
    variableName: manifest.variable_name,
    dimensionNames: manifest.dimension_names,
    ncUrl: `/api/supermap-voxel-netcdf-exports/${encodeURIComponent(exportId)}/volume.nc`,
    boundsDeg: manifest.layer_bounds_degrees,
    zBounds: manifest.z_bounds_metres,
    valueRange: manifest.encoded_value_range || manifest.value_range,
    identity: {
      resultId: manifest.candidate_result_id,
      gridSha256: manifest.grid_sha256,
      netcdfSha256: manifest.netcdf_sha256,
    },
  };
}

function buildTransferFunctions(vmin, vmax) {
  const span = vmax - vmin;
  const at = (f) => vmin + span * f;
  const k = query.get('rgb255') === '1' ? 255 : 1; // 色带量纲 A/B（本构建包实测为准）
  const colors = new SuperMap3D.ColorTransferFunction();
  colors.addRGBPoint(at(0.0), 0.10 * k, 0.25 * k, 0.85 * k);
  colors.addRGBPoint(at(0.25), 0.10 * k, 0.80 * k, 0.80 * k);
  colors.addRGBPoint(at(0.5), 0.95 * k, 0.85 * k, 0.15 * k);
  colors.addRGBPoint(at(0.75), 0.95 * k, 0.35 * k, 0.10 * k);
  colors.addRGBPoint(at(1.0), 0.65 * k, 0.05 * k, 0.10 * k);
  const opacity = new SuperMap3D.PiecewiseFunction();
  opacity.addPoint(at(0.0), 0.0);
  opacity.addPoint(at(0.2), 0.05);
  opacity.addPoint(at(0.5), 0.2);
  opacity.addPoint(at(0.75), 0.55);
  opacity.addPoint(at(1.0), 0.9);
  return { colors, opacity };
}

async function boot() {
  renderStatus();
  POC.phase = 'loading';
  renderStatus();

  const cfg = await loadConfig();
  diag.ncUrl = cfg.ncUrl;
  POC.identity = cfg.identity;

  const viewer = new SuperMap3D.Viewer('container', {
    contextOptions: { contextType: 2 },
    animation: false,
    timeline: false,
  });
  window.__viewer = viewer;
  const scene = viewer.scenePromise ? await viewer.scenePromise : viewer.scene;
  window.__scene = scene;

  if (query.get('clean') === '1') {
    try {
      scene.skyBox.show = false;
      scene.skyAtmosphere.show = false;
      scene.sun.show = false;
      scene.globe.showGroundAtmosphere = false;
      // 体数据位于地下（z<0）：关闭地表椭球遮挡（§9.1 关闭底图的测试模式）
      scene.globe.show = false;
      if (query.get('bg') === 'blue' && scene.backgroundColor) {
        scene.backgroundColor = new SuperMap3D.Color(0.05, 0.1, 0.35, 1.0);
      } else if (scene.backgroundColor) {
        scene.backgroundColor = SuperMap3D.Color.BLACK;
      }
    } catch (e) { diag.notes.push('clean mode partial: ' + (e && e.message)); }
  }

  const layer = await scene.addVoxelGridLayer(cfg.ncUrl, cfg.variableName);
  POC.layerType = (layer.constructor && layer.constructor.name) || layer.type || 'unknown';
  diag.notes.push(`layer.type=${layer.type}`);
  window.__layer = layer;

  // 注意：本机构建包的 _computePosition 对 _dataBounds 再调 fromDegrees，
  // 故 layerBounds 必须赋「角度数值」的裸 Rectangle（不能用 fromDegrees，否则双重换算错位）。
  layer.layerBounds = new SuperMap3D.Rectangle(
    cfg.boundsDeg.west, cfg.boundsDeg.south, cfg.boundsDeg.east, cfg.boundsDeg.north);
  diag.notes.push('layerBounds 以裸角度赋值（本构建包 _computePosition 内部再做 fromDegrees）');
  const zOffset = Number(query.get('zoff') || 0); // 对照实验：整体上移出地表
  layer.zBounds = new SuperMap3D.Cartesian2(cfg.zBounds[0] + zOffset, cfg.zBounds[1] + zOffset);
  if (zOffset) diag.notes.push(`zoff=+${zOffset}（出地表对照）`);

  const frameWaited = await waitLayerFrameState(layer);
  diag.notes.push(`_frameState 第 ${frameWaited} 帧就绪（startRender 前置条件）`);
  await Promise.resolve(layer.startRender({
    variableName: cfg.variableName,
    xDimName: cfg.dimensionNames[0],
    yDimName: cfg.dimensionNames[1],
    zDimName: cfg.dimensionNames[2],
  }));
  const [vmin, vmax] = cfg.valueRange;
  const slabMode = query.get('slab') === '1'; // 判别实验：纯色全不透明厚板，排除传递函数/色带变量
  const { colors, opacity } = slabMode
    ? (() => {
        const c = new SuperMap3D.ColorTransferFunction();
        c.addRGBPoint(vmin, 0, 1, 0);
        c.addRGBPoint(vmax, 0, 1, 0);
        const o = new SuperMap3D.PiecewiseFunction();
        o.addPoint(vmin, 1.0);
        o.addPoint(vmax, 1.0);
        return { colors: c, opacity: o };
      })()
    : buildTransferFunctions(vmin, vmax);
  const applyDefaults = () => {
    layer.volumeRenderMode = SuperMap3D.VolumeRenderMode.VolumeRendering;
    layer.minFiltration = vmin;
    layer.maxFiltration = vmax;
    layer.opaqueRate = 1.0; // 注意：本构建包该属性不进 uniform（实测 no-op），透明度走 opacityTransferFunction
    layer.enableLighting = !slabMode;
    layer.useGradientOpacity = slabMode ? false : true;
    layer.colorTransferFunction = colors;
    layer.opacityTransferFunction = opacity;
    POC.renderMode = 'VolumeRendering';
    POC.thresholds = { min: layer.minFiltration, max: layer.maxFiltration };
  };
  applyDefaults();
  diag.notes.push(`ctf stops=[${vmin}..${vmax}] 5 点 0-1 浮点`);

  const centerLon = (cfg.boundsDeg.west + cfg.boundsDeg.east) / 2;
  const centerLat = (cfg.boundsDeg.south + cfg.boundsDeg.north) / 2;
  const centerZ = (cfg.zBounds[0] + cfg.zBounds[1]) / 2 + zOffset;
  const span = Math.max(
    (cfg.boundsDeg.east - cfg.boundsDeg.west) * 111320 * Math.cos((centerLat * Math.PI) / 180),
    (cfg.boundsDeg.north - cfg.boundsDeg.south) * 110540,
    cfg.zBounds[1] - cfg.zBounds[0]);
  const columbusMode = query.get('mode') === 'columbus';
  if (columbusMode) {
    // 单变量对照实验：COLUMBUS_VIEW 走 _computePosition 平面分支（_setDataBounds 原样使用）
    scene.mode = SuperMap3D.SceneMode.COLUMBUS_VIEW;
    diag.notes.push('scene.mode=COLUMBUS_VIEW（对照实验）');
  }
  const zoomToVolume = () => {
    if (columbusMode) {
      scene.camera.setView({
        destination: new SuperMap3D.Cartesian3(centerLon, centerLat - 0.004, span * 2.5),
        orientation: { heading: 0, pitch: -0.9, roll: 0 },
        convert: false,
      });
    } else {
      // lookAt 体数据中心：setView 只摆相机不指向目标，曾导致全部"黑屏"假阴性
      const target = SuperMap3D.Cartesian3.fromDegrees(centerLon, centerLat, centerZ);
      scene.camera.lookAt(target, new SuperMap3D.HeadingPitchRange(0.6, -0.9, span * 2.5));
    }
  };
  zoomToVolume();
  if (query.get('marker') === '1') {
    // 对照图元：同位置红色实体盒，验证场景渲染管线本身是否在画
    viewer.entities.add({
      position: SuperMap3D.Cartesian3.fromDegrees(centerLon, centerLat, centerZ),
      box: {
        dimensions: new SuperMap3D.Cartesian3(30, 30, 400),
        material: SuperMap3D.Color.RED.withAlpha(0.9),
      },
    });
    diag.notes.push('marker 红盒已加入（对照图元）');
  }

  // 控件
  const modeSel = document.getElementById('ctl-mode');
  const minIn = document.getElementById('ctl-min');
  const maxIn = document.getElementById('ctl-max');
  const opIn = document.getElementById('ctl-opacity');
  const gradIn = document.getElementById('ctl-gradient');
  const lightIn = document.getElementById('ctl-lighting');
  minIn.value = String(vmin);
  maxIn.value = String(vmax);
  modeSel.addEventListener('change', () => {
    const mode = SuperMap3D.VolumeRenderMode[modeSel.value];
    layer.volumeRenderMode = mode;
    POC.renderMode = modeSel.value;
    renderStatus();
  });
  minIn.addEventListener('change', () => { layer.minFiltration = Number(minIn.value); POC.thresholds.min = layer.minFiltration; renderStatus(); });
  maxIn.addEventListener('change', () => { layer.maxFiltration = Number(maxIn.value); POC.thresholds.max = layer.maxFiltration; renderStatus(); });
  opIn.addEventListener('input', () => {
    // 本构建包 opaqueRate 未接入着色器 uniform（实测 no-op）；
    // 不透明度经 opacityTransferFunction（→_opacityTexture）生效。
    const factor = Number(opIn.value);
    const o = new SuperMap3D.PiecewiseFunction();
    o.addPoint(vmin, 0.0);
    o.addPoint(vmin + (vmax - vmin) * 0.2, 0.05 * factor);
    o.addPoint(vmin + (vmax - vmin) * 0.5, 0.2 * factor);
    o.addPoint(vmin + (vmax - vmin) * 0.75, 0.55 * factor);
    o.addPoint(vmax, 0.9 * factor);
    layer.opacityTransferFunction = o;
  });
  gradIn.addEventListener('change', () => { layer.useGradientOpacity = gradIn.checked; });
  lightIn.addEventListener('change', () => { layer.enableLighting = lightIn.checked; });
  document.getElementById('ctl-reset').addEventListener('click', () => { applyDefaults(); minIn.value = String(vmin); maxIn.value = String(vmax); opIn.value = '1'; renderStatus(); });
  document.getElementById('ctl-zoom').addEventListener('click', zoomToVolume);

  await waitRenderSettled();
  POC.phase = 'rendered';
  renderStatus();
}

boot().catch((e) => pushError('BOOT_FAILED', (e && (e.stack || e.message)) || e));
