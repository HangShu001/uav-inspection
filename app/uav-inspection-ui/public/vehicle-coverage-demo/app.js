const phaseNames = ["地图就绪至选点", "选点至实拍完成"];
const recordedRun = globalThis.recordedRun;
const { referencePoints, coveredPoints, coverage: coveragePercent, times: captureTimes, viewpointIds } = recordedRun;
const percentLabel = index => coveragePercent[index].toFixed(2) + "%";
const referenceLabel = referencePoints.toLocaleString("zh-CN");

const trendTable = document.getElementById("trend-table");
for (const [round, points] of coveredPoints.entries()) {
  const row = trendTable.insertRow();
  row.insertCell().textContent = round ? "第 " + round + " 次" : "任务起点";
  row.insertCell().textContent = round ? viewpointIds[round - 1] : "—";
  row.insertCell().textContent = round ? "+" + (points - coveredPoints[round - 1]).toLocaleString("zh-CN") : "—";
  row.insertCell().textContent = points.toLocaleString("zh-CN");
  row.insertCell().textContent = percentLabel(round);
  const cell = row.insertCell();
  if (round) {
    const link = document.createElement("a");
    link.href = "#observation-" + round;
    link.textContent = "查看";
    link.setAttribute("aria-label", "查看第 " + round + " 次观测");
    cell.append(link);
  }
}

const trend = document.getElementById("coverage-trend");
new ResizeObserver(([entry]) => {
  const { width, height } = entry.contentRect;
  if (!width || !height) return;
  const scale = window.devicePixelRatio || 1;
  trend.width = Math.round(width * scale);
  trend.height = Math.round(height * scale);
  const ctx = trend.getContext("2d");
  ctx.scale(scale, scale);
  const left = 45;
  const right = width - 22;
  const top = 25;
  const bottom = height - 31;
  const x = round => left + (right - left) * round / (coveredPoints.length - 1);
  const y = ratio => bottom - (bottom - top) * ratio;
  ctx.font = '12px system-ui';
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  for (const percent of [0, 25, 50, 75, 100]) {
    const line = y(percent / 100);
    ctx.strokeStyle = "#dfe6f0";
    ctx.beginPath();
    ctx.moveTo(left, line);
    ctx.lineTo(right, line);
    ctx.stroke();
    ctx.fillStyle = "#536680";
    ctx.fillText(percent + "%", left - 8, line);
  }
  ctx.textAlign = "center";
  ctx.fillStyle = "#536680";
  coveredPoints.forEach((_, round) => ctx.fillText(round, x(round), bottom + 16));
  ctx.beginPath();
  ctx.moveTo(x(0), y(0));
  coveragePercent.slice(1).forEach((percent, index) => ctx.lineTo(x(index + 1), y(percent / 100)));
  ctx.strokeStyle = "#2456ed";
  ctx.lineWidth = 2.5;
  ctx.stroke();
  ctx.fillStyle = "#2456ed";
  coveragePercent.forEach((percent, round) => {
    ctx.beginPath();
    ctx.arc(x(round), y(percent / 100), 3.5, 0, 2 * Math.PI);
    ctx.fill();
  });
  ctx.textAlign = "right";
  ctx.fillText(percentLabel(coveragePercent.length - 1), right, y(coveragePercent.at(-1) / 100) - 12);
}).observe(trend);

function setupChoices(id, labels, render) {
  const container = document.getElementById(id);
  const buttons = labels.map((label, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "tab";
    button.textContent = label;
    container.append(button);
    button.addEventListener("click", () => select(index));
    return button;
  });
  function select(index) {
    buttons.forEach((button, candidate) => button.setAttribute("aria-pressed", String(index === candidate)));
    render(index);
  }
  select(0);
}

function drawBars(id, rows, max) {
  const bars = rows.map(({ name, value, formatted, highlight }) => {
    const row = document.createElement("div");
    const label = document.createElement("div");
    label.className = "bar-label";
    const text = document.createElement("span");
    text.textContent = name;
    const number = document.createElement("strong");
    number.textContent = formatted;
    label.append(text, number);
    const track = document.createElement("div");
    track.className = "track";
    track.setAttribute("aria-hidden", "true");
    const fill = document.createElement("span");
    fill.className = highlight ? "fill highlight" : "fill";
    fill.style.width = (value / max * 100) + "%";
    track.append(fill);
    row.append(label, track);
    return row;
  });
  document.getElementById(id).replaceChildren(...bars);
}

const timings = recordedRun.diagnostics ?? [];
const roundTotal = document.getElementById("round-total");
document.getElementById("diagnostics-elapsed").textContent = recordedRun.elapsedSeconds.toFixed(1) + " s";
document.getElementById("diagnostics-result").textContent = `${captureTimes.length} 次有效观测 · 覆盖率 ${percentLabel(captureTimes.length)}`;
document.getElementById("diagnostics-empty").hidden = timings.length > 0;
if (timings.length) {
  roundTotal.hidden = false;
  const scale = Math.max(1, ...timings.flatMap(({ seconds }) => seconds));
  const labels = timings.map((_, index) => `视点 ${index + 1}`);
  setupChoices("rounds", labels, index => {
    const { seconds, viewpointId } = timings[index];
    const total = seconds.reduce((sum, value) => sum + value, 0);
    roundTotal.textContent = `#${viewpointId} · ${total.toFixed(2)} s`;
    drawBars("time-bars", seconds.map((value, phase) => ({
      name: phaseNames[phase],
      value,
      formatted: value.toFixed(2) + " s",
      highlight: phase === 1,
    })), scale);
  });
}

const views = [...document.querySelectorAll(".module-view")];
const links = document.querySelectorAll("nav a");
const video = document.getElementById("replay-video");
const cameraVideoContext = document.getElementById("camera-video-frame").getContext("2d");
const cameraInsetContext = document.getElementById("camera-inset-frame").getContext("2d");
const cameraCrop = [1280, 120, 640, 480];
if (recordedRun.cameraVideo) {
  video.src = "assets/suv-synced.mp4";
  cameraVideoContext.canvas.hidden = false;
  document.body.classList.add("continuous-camera");
}
const home = document.getElementById("home");
const vehicleModule = document.getElementById("vehicle-module");

// Pixel regions in the composed 1280 × 720 recording.
const flightCrop = [605, 71, 658, 600];
const flight = document.getElementById("flight-frame");
const trajectory = document.getElementById("trajectory-frame");
const flightContext = flight.getContext("2d");
const routeCaption = document.getElementById("route-caption");
const replayPhase = document.getElementById("replay-phase");
const replayCoverage = document.getElementById("replay-coverage");
const replayCount = document.getElementById("replay-count");
const replayObservations = document.getElementById("replay-observations");
const replayProgress = document.getElementById("replay-progress");
replayProgress.max = referencePoints;
const rvizFrame = document.getElementById("rviz-frame");
const updateCloudCoverage = globalThis.rvizCloud && createRvizCloud(globalThis.rvizCloud, recordedRun);
rvizFrame.hidden = Boolean(updateCloudCoverage);
const cameraFrame = document.getElementById("camera-frame");
const cameraPlaceholder = document.getElementById("camera-placeholder");
const cameraInfo = document.getElementById("camera-info");
const replayGain = document.getElementById("replay-gain");
const replayViewpoint = document.getElementById("replay-viewpoint");
const playButton = document.getElementById("replay-play");
const position = document.getElementById("replay-position");
const timeLabel = document.getElementById("replay-time");
const replayError = document.getElementById("replay-error");

function bindReplaySwitch(id, select) {
  const buttons = [...document.getElementById(id).querySelectorAll("button")];
  for (const button of buttons) {
    button.addEventListener("click", () => {
      for (const choice of buttons) choice.setAttribute("aria-pressed", String(choice === button));
      select(button.dataset.view);
    });
  }
}

bindReplaySwitch("media-switch", view => {
  document.getElementById("flight-view").hidden = view !== "flight";
  document.getElementById("camera-view").hidden = view !== "camera";
});
bindReplaySwitch("mobile-switch", view => {
  document.getElementById("replay").dataset.mobileView = view;
});
const observationCount = captureTimes.length;
document.getElementById("viewpoint-count").textContent = observationCount + " 个";
const finalPoints = coveredPoints.at(-1).toLocaleString("zh-CN") + " / " + referenceLabel;
document.getElementById("summary-coverage").textContent = percentLabel(observationCount);
document.getElementById("summary-points").textContent = finalPoints + " 点";
document.getElementById("summary-remaining").textContent = (referencePoints - coveredPoints.at(-1)).toLocaleString("zh-CN");
const seconds = Math.round(recordedRun.elapsedSeconds);
document.getElementById("summary-time").textContent = Math.floor(seconds / 60) + " 分 " + seconds % 60 + " 秒";
document.getElementById("trend-summary").textContent = observationCount + " 次有效观测共覆盖 " + finalPoints + " 个参考表面点。";
document.getElementById("replay-length").textContent = Math.round(recordedRun.videoDuration) + " 秒";
position.max = recordedRun.videoDuration;
const durationLabel = seconds => Math.floor(seconds / 60) + ":" + String(Math.floor(seconds % 60)).padStart(2, "0");

const captureButtons = captureTimes.map((time, index) => {
  const button = document.createElement("button");
  button.className = "tab";
  button.type = "button";
  const name = document.createElement("strong");
  name.textContent = "视点 " + (index + 1);
  const detail = document.createElement("span");
  detail.textContent = "#" + viewpointIds[index] + " · " + durationLabel(time);
  button.append(name, detail);
  button.addEventListener("click", () => { video.currentTime = time; });
  document.getElementById("replay-views").append(button);
  return button;
});

function drawVideoRegion(ctx, crop) {
  const { width, height } = ctx.canvas;
  const scale = Math.min(width / crop[2], height / crop[3]);
  const frameWidth = crop[2] * scale;
  const frameHeight = crop[3] * scale;
  ctx.clearRect(0, 0, width, height);
  ctx.drawImage(video, ...crop, (width - frameWidth) / 2, (height - frameHeight) / 2, frameWidth, frameHeight);
}

const cameraPositions = recordedRun.cameraPositions;
const [vehicleX, vehicleY] = recordedRun.vehicleCenter;
const [vehicleLength, vehicleWidth] = recordedRun.vehicleDimensions;
const xBounds = [...cameraPositions.map(point => point[0]), vehicleX - vehicleLength / 2, vehicleX + vehicleLength / 2];
const yBounds = [...cameraPositions.map(point => point[1]), vehicleY - vehicleWidth / 2, vehicleY + vehicleWidth / 2];
const xMin = Math.min(...xBounds), xMax = Math.max(...xBounds);
const yMin = Math.min(...yBounds), yMax = Math.max(...yBounds);
const routeSize = new WeakMap();

function routeProjection(canvas) {
  const { width, height, density } = routeSize.get(canvas) ?? { width: canvas.width, height: canvas.height, density: 1 };
  const scale = Math.max(1, Math.min((width - 54) / Math.max(1, xMax - xMin), (height - 60) / Math.max(1, yMax - yMin)));
  const routeX = x => width / 2 + (x - (xMin + xMax) / 2) * scale;
  const routeY = y => height / 2 - (y - (yMin + yMax) / 2) * scale;
  return { width, height, density, scale, routeX, routeY, points: cameraPositions.map(([x, y]) => [routeX(x), routeY(y)]) };
}

function drawRoute(canvas, observed) {
  const ctx = canvas.getContext("2d");
  const { width, height, density, scale, routeX, routeY, points: routePoints } = routeProjection(canvas);
  const plotLeft = 21, plotRight = width - 12, plotTop = 21, plotBottom = height - 24;
  ctx.setTransform(density, 0, 0, density, 0, 0);
  ctx.fillStyle = "#f3faff";
  ctx.fillRect(0, 0, width, height);
  ctx.font = "12px system-ui";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  for (let x = Math.floor(xMin) - 10; x <= Math.ceil(xMax) + 10; x++) {
    const px = routeX(x);
    if (px < plotLeft || px > plotRight) continue;
    ctx.fillStyle = "#d4e7ef";
    ctx.fillRect(px, plotTop, 1, plotBottom - plotTop);
    ctx.fillStyle = "#526980";
    if (x % 2 === 0) ctx.fillText(x, px, plotBottom + 12);
  }
  for (let y = Math.floor(yMin) - 10; y <= Math.ceil(yMax) + 10; y++) {
    const py = routeY(y);
    if (py < plotTop || py > plotBottom) continue;
    ctx.fillStyle = "#d4e7ef";
    ctx.fillRect(plotLeft, py, plotRight - plotLeft, 1);
    ctx.fillStyle = "#526980";
    if (y % 2 === 0) ctx.fillText(y, 12, py);
  }
  ctx.fillText("X (m)", width - 24, height - 7);
  ctx.fillText("Y (m)", 24, 9);
  ctx.beginPath();
  ctx.roundRect(routeX(vehicleX - vehicleLength / 2), routeY(vehicleY + vehicleWidth / 2), vehicleLength * scale, vehicleWidth * scale, 8);
  ctx.fillStyle = "#dbeafe";
  ctx.fill();
  ctx.strokeStyle = "#87afd0";
  ctx.stroke();
  ctx.fillStyle = "#244766";
  ctx.fillText("SUV", routeX(vehicleX), routeY(vehicleY));

  for (const [count, color, dash] of [[routePoints.length, "#7896ad", [5, 5]], [observed, "#087eaa", []]]) {
    if (!count) continue;
    ctx.beginPath();
    ctx.moveTo(...routePoints[0]);
    routePoints.slice(1, count).forEach(point => ctx.lineTo(...point));
    ctx.strokeStyle = color;
    ctx.lineWidth = dash.length ? 2 : 3;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.setLineDash(dash);
    ctx.stroke();
  }
  ctx.setLineDash([]);
  routePoints.forEach(([x, y], index) => {
    const active = index + 1 === observed;
    const seen = index < observed;
    ctx.beginPath();
    ctx.arc(x, y, active ? 13 : 10, 0, Math.PI * 2);
    ctx.fillStyle = active ? "#facc15" : seen ? "#087eaa" : "#f8fafc";
    ctx.fill();
    ctx.strokeStyle = active ? "#8a5508" : seen ? "#fff" : "#7896ad";
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.font = "700 13px system-ui";
    ctx.fillStyle = active ? "#422006" : seen ? "#fff" : "#334e67";
    ctx.fillText(index + 1, x, y);
  });
}

const analysisRoute = document.getElementById("analysis-route");
const routeObserver = new ResizeObserver(entries => {
  for (const { target, contentRect } of entries) {
    if (!contentRect.width || !contentRect.height) continue;
    const { width, height } = contentRect;
    const density = Math.max(2, window.devicePixelRatio || 1);
    routeSize.set(target, { width, height, density });
    target.width = Math.round(width * density);
    target.height = Math.round(height * density);
    drawRoute(target, target === trajectory ? Math.max(0, shownObservation) : observationCount);
  }
});
routeObserver.observe(trajectory);
routeObserver.observe(analysisRoute);
drawRoute(analysisRoute, observationCount);
trajectory.addEventListener("click", event => {
  const box = trajectory.getBoundingClientRect();
  const { width, height, points } = routeProjection(trajectory);
  const x = (event.clientX - box.left) * width / box.width;
  const y = (event.clientY - box.top) * height / box.height;
  const distances = points.map(([px, py]) => Math.hypot(px - x, py - y));
  const nearest = Math.min(...distances);
  if (nearest <= 17) video.currentTime = captureTimes[distances.indexOf(nearest)];
});

let shownObservation = -1;
function updateReplay() {
  const time = video.currentTime;
  const observations = captureTimes.filter(capturedAt => time >= capturedAt).length;
  if (video.readyState >= 2) {
    drawVideoRegion(flightContext, flightCrop);
    if (recordedRun.cameraVideo) {
      drawVideoRegion(cameraVideoContext, cameraCrop);
      drawVideoRegion(cameraInsetContext, cameraCrop);
      cameraInsetContext.canvas.parentElement.hidden = false;
    }
  }
  if (shownObservation !== observations) {
    showObservation(observations);
    shownObservation = observations;
  }
  position.value = time;
  timeLabel.textContent = durationLabel(time) + " / " + durationLabel(recordedRun.videoDuration);
}

function showObservation(observations) {
  const covered = coveredPoints[observations];
  const viewpoint = viewpointIds[observations - 1];
  drawRoute(trajectory, observations);
  routeCaption.textContent = observations
    ? "视点 " + viewpoint + " · 相机高度 " + recordedRun.cameraPositions[observations - 1][2].toFixed(2) + " m"
    : "实线为已回放，点击编号可跳转";
  if (updateCloudCoverage) updateCloudCoverage(observations);
  else rvizFrame.src = "assets/observations/rviz-" + observations + ".png";
  if (!recordedRun.cameraVideo && observations) cameraFrame.src = "assets/observations/camera-" + observations + ".jpg";
  cameraFrame.hidden = recordedRun.cameraVideo || !observations;
  cameraPlaceholder.hidden = Boolean(recordedRun.cameraVideo || observations);
  cameraInfo.textContent = recordedRun.cameraVideo ? "D435i · 同步录像" : observations ? "视点 " + viewpoint + " · 第 " + observations + " 次有效拍摄" : "等待首个视点拍摄";
  replayPhase.textContent = observations ? "第 " + observations + " 次有效观测 · 视点 " + viewpoint : "巡检起点";
  replayCoverage.textContent = percentLabel(observations);
  replayCount.textContent = covered.toLocaleString("zh-CN") + " / " + referenceLabel + " 点";
  replayObservations.textContent = observations + " / " + captureTimes.length;
  replayViewpoint.textContent = viewpoint ?? "—";
  replayGain.textContent = observations ? "+" + (covered - coveredPoints[observations - 1]).toLocaleString("zh-CN") + " 点" : "—";
  replayProgress.value = covered;
  captureButtons.forEach((button, index) => {
    if (index + 1 === observations) button.setAttribute("aria-current", "step");
    else button.removeAttribute("aria-current");
  });
}

let frameRequest;
function animateReplay() {
  updateReplay();
  if (!video.paused && !video.ended) frameRequest = requestAnimationFrame(animateReplay);
}

video.addEventListener("loadeddata", updateReplay);
video.addEventListener("seeked", updateReplay);
video.addEventListener("play", () => {
  playButton.textContent = "Ⅱ";
  playButton.title = "暂停视频";
  playButton.setAttribute("aria-label", playButton.title);
  cancelAnimationFrame(frameRequest);
  animateReplay();
});
function stopAnimation() {
  cancelAnimationFrame(frameRequest);
  playButton.textContent = "▶";
  playButton.title = video.ended ? "重播视频" : "播放视频";
  playButton.setAttribute("aria-label", playButton.title);
  updateReplay();
}
video.addEventListener("pause", stopAnimation);
video.addEventListener("ended", stopAnimation);
video.addEventListener("error", () => { replayError.textContent = "视频加载失败，请确认素材文件可用。"; });
playButton.addEventListener("click", () => {
  if (!video.paused) {
    video.pause();
    return;
  }
  if (video.ended) video.currentTime = 0;
  video.play().catch(() => { replayError.textContent = "无法播放，请重试或下载原视频。"; });
});
position.addEventListener("input", () => { video.currentTime = Number(position.value); });
document.getElementById("replay-restart").addEventListener("click", () => {
  video.currentTime = 0;
  video.play().catch(() => { replayError.textContent = "无法重新播放。"; });
});
document.getElementById("settings-open").addEventListener("click", () => document.getElementById("playback-settings").showModal());
document.getElementById("playback-rate").addEventListener("input", event => {
  video.playbackRate = Number(event.target.value);
  document.getElementById("playback-rate-value").textContent = video.playbackRate.toFixed(1) + "×";
});
updateReplay();

function showView() {
  const hash = location.hash.slice(1);
  const observation = Number(/^observation-(\d+)$/.exec(hash)?.[1]);
  const captureTime = captureTimes[observation - 1];
  const viewId = hash === "replay" || captureTime !== undefined ? "workbench" : views.some(view => view.id === hash) ? hash : "home";
  home.hidden = viewId !== "home";
  vehicleModule.hidden = viewId === "home";
  document.getElementById("module-link").hidden = viewId === "home";
  views.forEach(view => { view.hidden = view.id !== viewId; });
  for (const link of links) {
    if (link.hash === "#" + viewId || (link.id === "module-link" && viewId !== "home")) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  if (viewId !== "workbench") video.pause();
  if (captureTime !== undefined) video.currentTime = captureTime;
  if (hash === "replay" || captureTime !== undefined) document.getElementById("replay").scrollIntoView();
  else window.scrollTo(0, 0);
}

window.addEventListener("hashchange", showView);
showView();
