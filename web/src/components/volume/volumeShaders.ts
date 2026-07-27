export const volumeVertexShader = /* glsl */ `
  out vec3 vPosition;
  void main() {
    vPosition = position;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`

export const volumeFragmentShader = /* glsl */ `
  precision highp float;
  precision highp sampler3D;

  uniform sampler3D uVolume;
  uniform float uThreshold;
  uniform float uOpacity;
  uniform float uStepCount;
  in vec3 vPosition;
  out vec4 outColor;

  vec2 intersectBox(vec3 origin, vec3 direction) {
    vec3 inverseDirection = 1.0 / direction;
    vec3 t0 = (-0.5 - origin) * inverseDirection;
    vec3 t1 = ( 0.5 - origin) * inverseDirection;
    vec3 tMin = min(t0, t1);
    vec3 tMax = max(t0, t1);
    return vec2(max(max(tMin.x, tMin.y), tMin.z),
                min(min(tMax.x, tMax.y), tMax.z));
  }

  vec3 transferColor(float value) {
    vec3 low = vec3(0.08, 0.22, 0.55);
    vec3 middle = vec3(0.10, 0.75, 0.58);
    vec3 high = vec3(0.96, 0.32, 0.08);
    return value < 0.5
      ? mix(low, middle, value * 2.0)
      : mix(middle, high, (value - 0.5) * 2.0);
  }

  void main() {
    vec3 rayOrigin = (inverse(modelMatrix) * vec4(cameraPosition, 1.0)).xyz;
    vec3 rayDirection = normalize(vPosition - rayOrigin);
    vec2 bounds = intersectBox(rayOrigin, rayDirection);
    if (bounds.x > bounds.y) discard;

    float start = max(bounds.x, 0.0);
    float distanceInVolume = max(bounds.y - start, 0.0);
    float stepLength = distanceInVolume / max(uStepCount, 1.0);
    vec3 position = rayOrigin + rayDirection * start;
    vec3 stepVector = rayDirection * stepLength;
    vec4 accumulated = vec4(0.0);

    for (int step = 0; step < 384; step += 1) {
      if (float(step) >= uStepCount || accumulated.a >= 0.985) break;
      vec3 texturePosition = position + vec3(0.5);
      float value = texture(uVolume, texturePosition).r;
      if (value >= uThreshold) {
        float density = smoothstep(uThreshold, 1.0, value);
        float alpha = density * uOpacity * 0.055;
        vec3 color = transferColor(value);
        accumulated.rgb += (1.0 - accumulated.a) * alpha * color;
        accumulated.a += (1.0 - accumulated.a) * alpha;
      }
      position += stepVector;
    }
    if (accumulated.a <= 0.001) discard;
    outColor = accumulated;
  }
`
