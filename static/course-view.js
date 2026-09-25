/* XCTimer course map for spectators: a 30-second fly-over along the course over 3D
 * terrain, mile marks lighting up as it passes, each repeat loop fading to its own
 * colour, then a zoom out to the whole course and confetti. */
(function () {
  "use strict";
  var CFG = JSON.parse(document.getElementById("cv-config").textContent);
  var G = window.CourseGeo;
  var $ = function (id) { return document.getElementById(id); };
  maplibregl.setWorkerUrl(CFG.worker);

  var FLY_MS = 30000, INTRO_MS = 2200, OUTRO_MS = 2600;
  var courses = CFG.data.courses;
  var reduce = !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  var cur = 0, A = null, raf = 0, timer = 0, running = false;
  var deco = [], mileEls = [], head = null, lastData = 0, shownLap = 1, hitMile = 0, brg = 0;

  function fc(f) { return { type: "FeatureCollection", features: f }; }
  function line(c, props) { return { type: "Feature", properties: props || {}, geometry: { type: "LineString", coordinates: c } }; }
  var lineLayout = { "line-join": "round", "line-cap": "round" };

  var map;
  try {
    map = new maplibregl.Map({
      container: "cv-map",
      style: {
        version: 8,
        sources: {
          sat: { type: "raster", tiles: [CFG.tiles.url], tileSize: 256, maxzoom: CFG.tiles.maxzoom,
                 attribution: CFG.tiles.attribution },
          dem: { type: "raster-dem", tiles: [CFG.dem], tileSize: 256, encoding: "terrarium",
                 maxzoom: 15, attribution: CFG.demAttribution },
          ghost: { type: "geojson", data: fc([]) },
          route: { type: "geojson", data: fc([]) }
        },
        layers: [
          { id: "sat", type: "raster", source: "sat" },
          { id: "ghost", type: "line", source: "ghost", layout: lineLayout,
            paint: { "line-color": "#ffffff", "line-width": 2, "line-opacity": 0.5, "line-dasharray": [1.5, 1.5] } },
          { id: "route-casing", type: "line", source: "route", layout: lineLayout,
            paint: { "line-color": "#0a1728", "line-width": 9, "line-opacity": 0.5 } },
          { id: "route", type: "line", source: "route", layout: lineLayout,
            paint: { "line-color": ["get", "color"], "line-width": ["get", "width"] } }
        ],
        terrain: { source: "dem", exaggeration: 1.35 }   // real hills, gently emphasised
      },
      center: courses[0].points[0], zoom: 14, maxPitch: 70, attributionControl: { compact: true }
    });
  } catch (e) {
    $("cv-stats").textContent = "This browser can't draw the map (WebGL is off or unavailable).";
    $("cv-skip").hidden = true;
    return;
  }
  map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "bottom-right");

  // Credits start tucked behind the ⓘ button (tap it to read them) instead of a long
  // banner across the bottom of the map.
  function tuckCredits() {
    var a = map.getContainer().querySelector(".maplibregl-ctrl-attrib");
    if (a) { a.removeAttribute("open"); a.classList.remove("maplibregl-compact-show"); }
  }
  map.once("load", tuckCredits);
  map.once("idle", tuckCredits);

  // A finger or mouse on the map means "let me look" -- stop flying and hand it over.
  ["mousedown", "touchstart", "wheel"].forEach(function (ev) {
    map.getCanvasContainer().addEventListener(ev, function () { if (running) stopHere(); }, { passive: true });
  });
  // Start on "load" (tiles in), but never leave a viewer staring at an empty sky: if a
  // slow imagery server holds that up, go after 6 s anyway and let tiles fill in mid-flight.
  var started = false;
  function go() {
    if (started) return;
    if (!map.isStyleLoaded()) { setTimeout(go, 250); return; }
    started = true;
    $("cv-loading").hidden = true;
    select(0, !reduce);
  }
  map.on("load", go);
  map.once("styledata", function () { setTimeout(go, 6000); });

  // ---------------------------------------------------------------- one course
  function select(i, fly) {
    halt();
    cur = i;
    var c = courses[i];
    A = G.analyse(c.points, c.smooth);
    $("cv-sub").textContent = courses.length > 1 ? c.name : "Course map";
    chips();
    stats();
    map.getSource("ghost").setData(fc([line(A.path)]));
    drawDeco();
    if (fly) flyover(); else overview(false);
  }

  function chips() {
    var box = $("cv-chips");
    box.innerHTML = "";
    if (courses.length < 2) return;
    courses.forEach(function (c, i) {
      var b = document.createElement("button");
      b.textContent = c.name;
      if (i === cur) b.className = "on";
      b.onclick = function () { select(i, !reduce); };
      box.appendChild(b);
    });
  }

  function stats() {
    var h = "<b>" + A.miles.toFixed(2) + "</b> mi · " + (A.meters / 1000).toFixed(2) + " km";
    if (A.loops > 1) {
      h += '<br><span class="cm-legend">';
      for (var i = 1; i <= A.loops; i++) h += '<span><i style="background:' + G.lapColor(i) + '"></i>Loop ' + i + "</span>";
      h += "</span>";
    }
    $("cv-stats").innerHTML = h;
  }

  function flag(cls, icon, text) {
    var el = document.createElement("div");
    el.className = "cflag " + cls;
    el.innerHTML = '<span class="fi">' + icon + "</span>" + text;
    return el;
  }

  function drawDeco() {
    deco.forEach(function (m) { m.remove(); });
    deco = []; mileEls = [];
    // Mile marks first: markers added later draw on top, and the flags matter more.
    A.marks.forEach(function (mk) {
      var el = document.createElement("div");
      el.className = "cmile";
      el.textContent = mk.mile + " mi";
      mileEls.push(el);
      deco.push(new maplibregl.Marker({ element: el }).setLngLat(mk.p).addTo(map));
    });
    if (G.hav(A.start, A.finish) < 25) {
      deco.push(new maplibregl.Marker({ element: flag("finish", "🏁", "Start / Finish"), anchor: "bottom" }).setLngLat(A.start).addTo(map));
    } else {
      // Close together (a finish chute beside the start line), the two flags would sit on
      // top of each other -- lean them apart instead.
      var near = G.hav(A.start, A.finish) < 120, west = A.start[0] < A.finish[0];
      deco.push(new maplibregl.Marker({ element: flag("start", "🟢", "Start"),
        anchor: near ? (west ? "bottom-right" : "bottom-left") : "bottom" }).setLngLat(A.start).addTo(map));
      deco.push(new maplibregl.Marker({ element: flag("finish", "🏁", "Finish"),
        anchor: near ? (west ? "bottom-left" : "bottom-right") : "bottom" }).setLngLat(A.finish).addTo(map));
    }
  }

  function setRoute(upto) {
    map.getSource("route").setData(fc(G.runs(A.samples, A.laps, upto).map(function (r) {
      return line(r.coords, { color: G.lapColor(r.pass), width: G.lapWidth(r.pass, 6) });
    })));
  }

  // ---------------------------------------------------------------- the fly-over
  function heading(d) {
    var a = G.pointAt(A.samples, Math.max(0, d - 20)).p, b = G.pointAt(A.samples, d + 70).p;
    return G.bearing(a, b);
  }
  function turn(from, to, k) {                  // ease the camera round, the short way
    var diff = ((to - from + 540) % 360) - 180;
    return (from + diff * k + 360) % 360;
  }
  function zoom() { return A.meters > 6000 ? 16.4 : 17; }   // low enough to see the runners' view
  function pad() { return { top: Math.round(window.innerHeight * 0.35), bottom: 0, left: 0, right: 0 }; }
  function toast(text) {
    var t = $("cv-toast");
    t.textContent = text;
    t.classList.add("on");
    clearTimeout(t._h);
    t._h = setTimeout(function () { t.classList.remove("on"); }, 1400);
  }

  function flyover() {
    halt();
    running = true;
    $("cv-skip").hidden = false; $("cv-replay").hidden = true;
    setRoute(0);
    hitMile = 0; shownLap = 1;
    mileEls.forEach(function (el) { el.classList.remove("hit", "done"); });
    var el = document.createElement("div");
    el.className = "cv-head";
    head = new maplibregl.Marker({ element: el }).setLngLat(A.start).addTo(map);
    brg = heading(0);
    map.flyTo({ center: A.start, zoom: zoom(), pitch: 62, bearing: brg, padding: pad(), duration: INTRO_MS, essential: true });
    toast("🟢 Start");
    timer = setTimeout(function () {
      if (!running) return;
      var t0 = performance.now();
      function frame(now) {
        if (!running) return;
        var f = Math.min(1, (now - t0) / FLY_MS);
        var d = f * A.meters;                              // constant speed, like a drone
        var p = G.pointAt(A.samples, d);
        brg = turn(brg, heading(d), 0.045);
        map.jumpTo({ center: p.p, bearing: brg, pitch: 62, zoom: zoom(), padding: pad() });
        head.setLngLat(p.p);
        if (now - lastData > 60 || f === 1) { setRoute(d); lastData = now; }
        while (hitMile < A.marks.length && d >= A.marks[hitMile].d) {
          var mel = mileEls[hitMile];
          mel.classList.add("hit");
          (function (x) { setTimeout(function () { x.classList.remove("hit"); x.classList.add("done"); }, 2200); })(mel);
          toast("Mile " + A.marks[hitMile].mile);
          hitMile++;
        }
        var lap = A.laps[p.i] || 1;
        if (lap > shownLap) {                               // a new loop begins: fade to its colour
          shownLap = lap;
          el.style.background = G.lapColor(lap);
          el.style.boxShadow = "0 0 0 6px " + G.lapColor(lap) + "55, 0 2px 6px rgba(0,0,0,.5)";
          toast("Loop " + lap);
        }
        if (f < 1) raf = requestAnimationFrame(frame);
        else { toast("🏁 Finish"); overview(true); }
      }
      raf = requestAnimationFrame(frame);
    }, INTRO_MS);
  }

  function bounds() {
    var b = new maplibregl.LngLatBounds(A.path[0], A.path[0]);
    A.path.forEach(function (p) { b.extend(p); });
    return b;
  }

  // Zoom out to the whole course; confetti when a fly-over just finished.
  function overview(celebrate) {
    halt();
    setRoute(null);
    mileEls.forEach(function (el) { el.classList.add("done"); });
    // Side room for the Start/Finish flags, which lean outward past the course itself.
    var cam = map.cameraForBounds(bounds(), { padding: { top: 110, bottom: 150, left: 85, right: 85 } });
    map.flyTo({ center: cam.center, zoom: cam.zoom - (celebrate ? 0.25 : 0), bearing: 0, pitch: celebrate ? 30 : 0,
                padding: { top: 0, bottom: 0, left: 0, right: 0 },
                duration: celebrate ? OUTRO_MS : 0, essential: true });
    if (celebrate) timer = setTimeout(confettiRain, OUTRO_MS - 400);
  }

  function stopHere() {             // the viewer grabbed the map: finish the line, keep their view
    halt();
    setRoute(null);
    mileEls.forEach(function (el) { el.classList.add("done"); });
  }

  function halt() {
    running = false;
    cancelAnimationFrame(raf);
    clearTimeout(timer);
    if (head) { head.remove(); head = null; }
    $("cv-skip").hidden = true;
    $("cv-replay").hidden = false;
  }

  var shoot = window.confetti ? window.confetti.create($("cv-confetti"), { resize: true, useWorker: false }) : null;
  function confettiRain() {
    if (!shoot || reduce) return;
    var colors = ["#ffd400", "#ff7a00", "#ff2d95", "#22d3ee", "#7CFC00", "#ffffff"];
    var end = Date.now() + 3200;
    (function drop() {                   // falling from the top edge, all the way across
      shoot({ particleCount: 4, angle: 270, spread: 80, startVelocity: 6, gravity: 0.65, ticks: 420,
              scalar: 1.1, drift: (Math.random() - 0.5) * 0.8, colors: colors,
              origin: { x: Math.random(), y: -0.05 } });
      if (Date.now() < end) requestAnimationFrame(drop);
    })();
  }

  $("cv-skip").onclick = function () { overview(false); };
  $("cv-replay").onclick = function () { flyover(); };
})();
