/**
 * Paint identity + landmark drawing helpers (testable without Human runtime).
 */

export function buildPaintCacheKey({
  gesturesEnabled,
  modelLoaded,
  realHandDetected,
  realCameraAccepted,
  backend,
  status,
  pose,
  conf,
  viewing,
  showLandmarks: showLm,
  observation,
  loading: isLoading,
}) {
  const obs = observation || {};
  const landmarks = Array.isArray(obs.landmarks) ? obs.landmarks : [];
  const landmarkSig = landmarks
    .map((p) => `${p && p.x != null ? Number(p.x).toFixed(1) : ''},${p && p.y != null ? Number(p.y).toFixed(1) : ''}`)
    .join(';');
  return JSON.stringify({
    gesturesEnabled,
    modelLoaded,
    realHandDetected,
    realCameraAccepted,
    backend,
    status,
    pose,
    conf,
    viewing,
    showLandmarks: !!showLm,
    loading: !!isLoading,
    obsAt: obs.at || 0,
    landmarkSig,
    sourceWidth: obs.sourceWidth || null,
    sourceHeight: obs.sourceHeight || null,
  });
}

export function drawLandmarks(canvas, landmarks, sourceWidth, sourceHeight) {
  if (!canvas) return false;
  const ctx = canvas.getContext('2d');
  if (!ctx) return false;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (!landmarks || !landmarks.length) return true;
  const srcW = sourceWidth > 0 ? sourceWidth : 640;
  const srcH = sourceHeight > 0 ? sourceHeight : 480;
  ctx.fillStyle = '#3ecf8e';
  for (const pt of landmarks) {
    if (!pt || pt.x == null || pt.y == null) continue;
    const x = (pt.x / srcW) * canvas.width;
    const y = (pt.y / srcH) * canvas.height;
    ctx.beginPath();
    ctx.arc(x, y, 2.5, 0, Math.PI * 2);
    ctx.fill();
  }
  return true;
}
