import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import type { PackedVolume } from './volumeGrid'
import { volumeFragmentShader, volumeVertexShader } from './volumeShaders'

export interface VolumeRuntime {
  setThreshold(value: number): void
  setOpacity(value: number): void
  dispose(): void
}

export function createVolumeRuntime(
  container: HTMLElement,
  grid: PackedVolume,
  threshold: number,
  opacity: number,
): VolumeRuntime {
  const canvas = document.createElement('canvas')
  canvas.dataset.test = 'volume-canvas'
  // inline canvas 的基线间隙会让容器随 setSize 无限长高（ResizeObserver 正反馈），必须 block
  canvas.style.display = 'block'
  const context = canvas.getContext('webgl2', {
    alpha: true,
    antialias: true,
    preserveDrawingBuffer: true,
  })
  if (!context) throw new Error('当前浏览器或显卡不支持 WebGL2')
  container.appendChild(canvas)

  const renderer = new THREE.WebGLRenderer({ canvas, context, alpha: true, antialias: true })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
  renderer.setClearColor(0x05070a, 1)

  let frame = 0
  let disposed = false
  let observer: ResizeObserver | null = null
  let controls: OrbitControls | null = null
  let texture: THREE.Data3DTexture | null = null
  let material: THREE.ShaderMaterial | null = null
  let geometry: THREE.BoxGeometry | null = null

  const releaseGpuResources = () => {
    cancelAnimationFrame(frame)
    observer?.disconnect()
    controls?.dispose()
    geometry?.dispose()
    material?.dispose()
    texture?.dispose()
    renderer.dispose()
    canvas.remove()
  }

  try {
    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(42, 1, 0.01, 100)
    camera.position.set(1.65, -2.2, 1.45)

    controls = new OrbitControls(camera, canvas)
    controls.enableDamping = true
    controls.target.set(0, 0, 0)

    const [nx, ny, nz] = grid.shape
    texture = new THREE.Data3DTexture(grid.bytes, nx, ny, nz)
    texture.format = THREE.RedFormat
    texture.type = THREE.UnsignedByteType
    texture.minFilter = THREE.LinearFilter
    texture.magFilter = THREE.LinearFilter
    texture.unpackAlignment = 1
    texture.needsUpdate = true

    const uniforms = {
      uVolume: { value: texture },
      uThreshold: { value: THREE.MathUtils.clamp(threshold, 0, 0.99) },
      uOpacity: { value: THREE.MathUtils.clamp(opacity, 0.01, 1) },
      uStepCount: { value: THREE.MathUtils.clamp(Math.max(nx, ny, nz) * 3, 64, 256) },
      uModelInverse: { value: new THREE.Matrix4() },
    }
    material = new THREE.ShaderMaterial({
      glslVersion: THREE.GLSL3,
      vertexShader: volumeVertexShader,
      fragmentShader: volumeFragmentShader,
      uniforms,
      side: THREE.BackSide,
      transparent: true,
      depthWrite: false,
    })

    const spans = grid.ranges.map(([min, max]) => max - min)
    if (spans.some((span) => !Number.isFinite(span) || !(span > 0))) {
      throw new Error(`invalid physical volume spans: ${spans.join(',')}`)
    }
    const scale = Math.max(...spans)
    geometry = new THREE.BoxGeometry(1, 1, 1)
    const mesh = new THREE.Mesh(geometry, material)
    mesh.scale.set(spans[0] / scale, spans[1] / scale, spans[2] / scale)
    scene.add(mesh)
    // 网格静态：创建时求一次逆模型矩阵，供片元着色器把相机变换到对象空间
    mesh.updateMatrixWorld()
    uniforms.uModelInverse.value.copy(mesh.matrixWorld).invert()

    const resize = () => {
      const width = Math.max(container.clientWidth, 1)
      const height = Math.max(container.clientHeight, 1)
      // updateStyle=false 时高 DPR 下 canvas 属性像素超过容器 CSS 尺寸，
      // ResizeObserver 会正反馈无限撑高（真实 Chromium 实测 33M px 黑屏）；
      // 默认 updateStyle=true 把 canvas CSS 尺寸钉在容器上，杜绝增长环。
      renderer.setSize(width, height)
      camera.aspect = width / height
      camera.updateProjectionMatrix()
    }
    const animate = () => {
      if (disposed) return
      controls?.update()
      renderer.render(scene, camera)
      frame = requestAnimationFrame(animate)
    }
    observer = new ResizeObserver(resize)
    observer.observe(container)
    resize()
    animate()

    return {
      setThreshold(value) {
        uniforms.uThreshold.value = THREE.MathUtils.clamp(value, 0, 0.99)
      },
      setOpacity(value) {
        uniforms.uOpacity.value = THREE.MathUtils.clamp(value, 0.01, 1)
      },
      dispose() {
        if (disposed) return
        disposed = true
        releaseGpuResources()
      },
    }
  } catch (error) {
    disposed = true
    try {
      releaseGpuResources()
    } catch {
      // 清理异常不得覆盖构造错误
    }
    throw error
  }
}
