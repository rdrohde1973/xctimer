/* XCTimer course map for spectators: a fly-over along the course (25 s a mile) over 3D
 * terrain under a hazy sky, a glowing comet trail behind the dot, mile marks (and road
 * water stations) lighting up as it passes, each repeat loop fading to its own colour, an
 * elevation profile tracking along the bottom, then a zoom out and confetti. */
(function () {
  "use strict";
  var CFG = JSON.parse(document.getElementById("cv-config").textContent);
  var G = window.CourseGeo;
  var $ = function (id) { return document.getElementById(id); };
  maplibregl.setWorkerUrl(CFG.worker);

  // A steady 25 seconds a mile: slow enough not to make anyone dizzy, and a 5K takes
  // longer than a 2 mile instead of racing through it in the same time.
  var MS_PER_MILE = 25000, INTRO_MS = 2200, OUTRO_MS = 2600;
  var courses = CFG.data.courses;
  var reduce = !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  var cur = 0, A = null, raf = 0, timer = 0, running = false;
  var deco = [], mileEls = [], head = null, lastData = 0, shownLap = 1, hitMile = 0, brg = 0;
  // The comet tail: short and thin, so it sparkles behind the dot without washing the
  // loop colour out to white (140 m did).
  var waters = [], waterEls = [], hitWater = 0, TRAIL = 45;

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
          route: { type: "geojson", data: fc([]) },
          trail: { type: "geojson", data: fc([]), lineMetrics: true }   // lineMetrics: for the fade
        },
        layers: [
          { id: "sat", type: "raster", source: "sat" },
          { id: "ghost", type: "line", source: "ghost", layout: lineLayout,
            paint: { "line-color": "#ffffff", "line-width": 2, "line-opacity": 0.5, "line-dasharray": [1.5, 1.5] } },
          // A soft glow in each loop's colour under the line.
          { id: "route-glow", type: "line", source: "route", layout: lineLayout,
            paint: { "line-color": ["get", "color"], "line-width": ["+", ["get", "width"], 14],
                     "line-blur": 9, "line-opacity": 0.5 } },
          { id: "route-casing", type: "line", source: "route", layout: lineLayout,
            paint: { "line-color": "#0a1728", "line-width": 11, "line-opacity": 0.5 } },
          { id: "route", type: "line", source: "route", layout: lineLayout,
            paint: { "line-color": ["get", "color"], "line-width": ["get", "width"] } },
          // The comet: the last stretch behind the dot, fading in to bright white at the dot.
          { id: "trail-glow", type: "line", source: "trail", layout: lineLayout,
            paint: { "line-width": 12, "line-blur": 8,
                     "line-gradient": ["interpolate", ["linear"], ["line-progress"],
                                       0, "rgba(255,255,255,0)", 0.6, "rgba(255,255,255,0.1)",
                                       1, "rgba(255,255,255,0.5)"] } },
          { id: "trail", type: "line", source: "trail", layout: lineLayout,
            paint: { "line-width": 3.5, "line-blur": 1,
                     "line-gradient": ["interpolate", ["linear"], ["line-progress"],
                                       0, "rgba(255,255,255,0)", 0.6, "rgba(255,255,255,0.2)",
                                       1, "rgba(255,255,255,0.9)"] } }
        ],
        terrain: { source: "dem", exaggeration: 1.35 },  // real hills, gently emphasised
        // Tilted, the map used to stop at a hard edge; now it fades into haze and sky.
        sky: { "sky-color": "#3f86d4", "horizon-color": "#d6e8f5", "fog-color": "#e2edf6",
               "sky-horizon-blend": 0.55, "horizon-fog-blend": 0.6, "fog-ground-blend": 0.82 }
      },
      center: courses[0].points[0], zoom: 14, maxPitch: 70, attributionControl: false
    });
  } catch (e) {
    $("cv-stats").textContent = "This browser can't draw the map (WebGL is off or unavailable).";
    $("cv-skip").hidden = true;
    return;
  }
  // Controls live top-right: the bottom is the elevation strip and the stats.
  map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-right");
  map.addControl(new maplibregl.AttributionControl({ compact: true }), "top-right");

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
    // Water stations (road events): placed by how far along the route each one sits.
    waters = (c.water || []).map(function (w) { return { p: w, d: G.along(A.samples, w).d }; })
      .sort(function (a, b) { return a.d - b.d; });
    $("cv-sub").textContent = courses.length > 1 ? c.name : "Course map";
    chips();
    stats();
    map.getSource("ghost").setData(fc([line(A.path)]));
    drawDeco();
    profile();
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
    var h = '<b id="cv-mi"></b> mi · <span id="cv-km"></span> km';
    if (A.loops > 1) {
      h += '<br><span class="cm-legend">';
      for (var i = 1; i <= A.loops; i++) h += '<span><i style="background:' + G.lapColor(i) + '"></i>Loop ' + i + "</span>";
      h += "</span>";
    }
    if (waters.length) {
      h += '<br><span class="cv-water-list">💧 Water at ' + waters.map(function (w) {
        return (w.d / G.MILE).toFixed(1); }).join(" · ") + " mi</span>";
    }
    $("cv-stats").innerHTML = h;
    dist(A.meters);
  }
  // The distance readout: counts up with the dot during the fly-over, the full course otherwise.
  function dist(m) {
    $("cv-mi").textContent = (m / G.MILE).toFixed(2);
    $("cv-km").textContent = (m / 1000).toFixed(2);
  }

  function flag(cls, icon, text) {
    var el = document.createElement("div");
    el.className = "cflag " + cls;
    el.innerHTML = '<span class="fi">' + icon + "</span>" + text;
    return el;
  }

  function drawDeco() {
    deco.forEach(function (m) { m.remove(); });
    deco = []; mileEls = []; waterEls = [];
    // Mile marks first: markers added later draw on top, and the flags matter more.
    A.marks.forEach(function (mk) {
      var el = document.createElement("div");
      el.className = "cmile";
      el.textContent = mk.mile + " mi";
      mileEls.push(el);
      deco.push(new maplibregl.Marker({ element: el }).setLngLat(mk.p).addTo(map));
    });
    waters.forEach(function (w) {
      var el = flag("water", "💧", "Water");
      waterEls.push(el);
      deco.push(new maplibregl.Marker({ element: el, anchor: "bottom" }).setLngLat(w.p).addTo(map));
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
    map.getSource("route").setData(fc(G.runs(A.samples, A.laps, upto, A.loop).map(function (r) {
      return line(r.coords, { color: G.lapColor(r.loop), width: G.lapWidth(r.pass, 8) });
    })));
  }

  function setTrail(d, i) {
    if (d == null) { map.getSource("trail").setData(fc([])); return; }
    var from = Math.max(0, d - TRAIL), c = [G.pointAt(A.samples, d).p];
    for (var j = i; j >= 0 && A.samples[j].d > from; j--) c.push(A.samples[j].p);
    c.push(G.pointAt(A.samples, from).p);
    c.reverse();                                  // tail first, so progress 1 is at the dot
    map.getSource("trail").setData(fc(c.length > 2 || d > 1 ? [line(c)] : []));
  }

  // ---------------------------------------------------------------- elevation profile
  var tiles = {}, EZ = 15;
  function tile(x, y) {
    var k = x + "/" + y;
    if (!tiles[k]) {
      tiles[k] = fetch(CFG.dem.replace("{z}", EZ).replace("{x}", x).replace("{y}", y))
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.blob(); })
        .then(function (b) { return createImageBitmap(b); })
        .then(function (bm) {
          var cv = document.createElement("canvas");
          cv.width = bm.width; cv.height = bm.height;
          var cx = cv.getContext("2d", { willReadFrequently: true });
          cx.drawImage(bm, 0, 0);
          return cx.getImageData(0, 0, bm.width, bm.height).data;
        });
    }
    return tiles[k];
  }
  function elevAt(px, data) {                    // bilinear inside one 256 px tile
    var x = ((px[0] % 256) + 256) % 256, y = ((px[1] % 256) + 256) % 256;
    var x0 = Math.min(254, Math.floor(x)), y0 = Math.min(254, Math.floor(y)), fx = x - x0, fy = y - y0;
    function e(xx, yy) { var o = (yy * 256 + xx) * 4; return G.terrarium(data[o], data[o + 1], data[o + 2]); }
    return (e(x0, y0) * (1 - fx) + e(x0 + 1, y0) * fx) * (1 - fy) + (e(x0, y0 + 1) * (1 - fx) + e(x0 + 1, y0 + 1) * fx) * fy;
  }
  function ft(m) { return Math.round(m * 3.28084).toLocaleString(); }
  function profile() {
    var box = $("cv-elev"), mine = A;
    box.hidden = true;
    document.body.classList.remove("has-elev");
    if (!window.fetch || !window.createImageBitmap || !A.samples.length) return;
    var px = A.samples.map(function (s) { return G.worldPx(s.p, EZ); });
    var keys = {};
    px.forEach(function (q) { keys[Math.floor(q[0] / 256) + "/" + Math.floor(q[1] / 256)] = 1; });
    var list = Object.keys(keys);
    if (list.length > 40) return;                // something's wrong with the course; skip it
    Promise.all(list.map(function (k) { var a = k.split("/"); return tile(+a[0], +a[1]); })).then(function (datas) {
      if (A !== mine) return;                    // the viewer switched course meanwhile
      var by = {};
      list.forEach(function (k, n) { by[k] = datas[n]; });
      var el = px.map(function (q) { return elevAt(q, by[Math.floor(q[0] / 256) + "/" + Math.floor(q[1] / 256)]); });
      A.elev = el;
      A.hills = G.hills(el, A.samples);
      drawProfile();
    }).catch(function () { /* no elevation: the strip just stays hidden */ });
  }
  function drawProfile() {
    var H = A.hills, el = A.elev, W = 1000, T = 60, n = el.length;
    var lo = H.lo, hi = Math.max(H.hi, H.lo + 30);   // at least 100 ft tall: a gentle course LOOKS gentle
    function X(d) { return d / A.meters * W; }
    function Y(e) { return 4 + (1 - (e - lo) / (hi - lo)) * (T - 8); }
    var step = Math.max(1, Math.floor(n / 400)), pts = [];
    for (var i = 0; i < n; i += step) pts.push(X(A.samples[i].d).toFixed(1) + "," + Y(el[i]).toFixed(1));
    pts.push(X(A.meters).toFixed(1) + "," + Y(el[n - 1]).toFixed(1));
    var climb = "";
    if (H.climb && H.climb.rise >= 3) {           // under 10 ft isn't a hill worth naming
      var cp = [];
      for (var k = 0; k < n; k += step) {
        var d = A.samples[k].d;
        if (d >= H.climb.from && d <= H.climb.to) cp.push(X(d).toFixed(1) + "," + Y(el[k]).toFixed(1));
      }
      if (cp.length > 1) climb = '<polyline points="' + cp.join(" ") + '" fill="none" stroke="#c084fc" stroke-width="4" vector-effect="non-scaling-stroke" stroke-linejoin="round"/>';
    }
    var ticks = A.marks.map(function (mk) {
      return '<line x1="' + X(mk.d) + '" x2="' + X(mk.d) + '" y1="0" y2="' + T + '" stroke="rgba(255,255,255,.25)" stroke-width="1" vector-effect="non-scaling-stroke"/>';
    }).join("");
    $("cv-elev-svg").innerHTML =
      '<defs><linearGradient id="cvg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#38bdf8" stop-opacity=".55"/>' +
      '<stop offset="1" stop-color="#38bdf8" stop-opacity=".05"/></linearGradient></defs>' + ticks +
      '<polygon points="0,' + T + " " + pts.join(" ") + " " + W + "," + T + '" fill="url(#cvg)"/>' +
      '<polyline points="' + pts.join(" ") + '" fill="none" stroke="#fff" stroke-width="2" vector-effect="non-scaling-stroke" stroke-linejoin="round"/>' + climb;
    var tags = "";
    if (climb) {
      // Label sits just above the top of the climb, kept inside the strip at either end.
      var at = H.climb.to / A.meters * 100, top = Y(H.hi) / T * 100;
      var k2 = 0;
      while (k2 < n - 1 && A.samples[k2].d < H.climb.to) k2++;
      top = Y(el[k2]) / T * 100;
      var sx = at > 80 ? "-100%" : at < 20 ? "0" : "-50%";
      tags += '<span class="cv-elev-tag" style="left:' + at.toFixed(1) + "%;top:" + top.toFixed(1) +
              "%;transform:translate(" + sx + ',-125%)">⛰ ' + ft(H.climb.rise) + " ft climb</span>";
    }
    waters.forEach(function (w) {
      tags += '<span class="cv-elev-drop" style="left:' + (w.d / A.meters * 100).toFixed(1) + '%">💧</span>';
    });
    $("cv-elev-tags").innerHTML = tags;
    $("cv-elev-head").innerHTML = "<b>Elevation</b><span>↑ " + ft(H.gain) + " ft of climbing · " +
      ft(H.lo) + "–" + ft(H.hi) + " ft</span>";
    $("cv-elev").hidden = false;
    document.body.classList.add("has-elev");
    elevDot(null);
  }
  function elevDot(d) {                          // the dot on the profile, in step with the map
    var dot = $("cv-elev-dot");
    if (d == null || !A.elev) { dot.hidden = true; return; }
    var p = G.pointAt(A.samples, d), H = A.hills, hi = Math.max(H.hi, H.lo + 30);
    var e = A.elev[p.i];
    dot.hidden = false;
    dot.style.left = (d / A.meters * 100) + "%";
    dot.style.top = ((4 + (1 - (e - H.lo) / (hi - H.lo)) * 52) / 60 * 100) + "%";
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
  function zoom() { return 17.6; }       // close in, near the runners' view
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
    hitMile = 0; shownLap = 1; hitWater = 0;
    dist(0);
    waterEls.forEach(function (el) { el.classList.remove("hit"); });
    mileEls.forEach(function (el) { el.classList.remove("hit", "done"); });
    var el = document.createElement("div");
    el.className = "cv-head";
    el.style.background = G.lapColor(1);
    el.style.boxShadow = "0 0 0 6px " + G.lapColor(1) + "55, 0 2px 6px rgba(0,0,0,.5)";
    head = new maplibregl.Marker({ element: el }).setLngLat(A.start).addTo(map);
    brg = heading(0);
    map.flyTo({ center: A.start, zoom: zoom(), pitch: 62, bearing: brg, padding: pad(), duration: INTRO_MS, essential: true });
    toast("🟢 Start");
    timer = setTimeout(function () {
      if (!running) return;
      var t0 = performance.now();
      function frame(now) {
        if (!running) return;
        var f = Math.min(1, (now - t0) / (MS_PER_MILE * A.miles));
        var d = f * A.meters;                              // constant speed, like a drone
        var p = G.pointAt(A.samples, d);
        brg = turn(brg, heading(d), 0.03);          // turn gently -- quick swings are what make you dizzy
        map.jumpTo({ center: p.p, bearing: brg, pitch: 62, zoom: zoom(), padding: pad() });
        head.setLngLat(p.p);
        dist(d);
        setTrail(d, p.i);
        elevDot(d);
        if (now - lastData > 60 || f === 1) { setRoute(d); lastData = now; }
        while (hitMile < A.marks.length && d >= A.marks[hitMile].d) {
          var mel = mileEls[hitMile];
          mel.classList.add("hit");
          (function (x) { setTimeout(function () { x.classList.remove("hit"); x.classList.add("done"); }, 2200); })(mel);
          toast("Mile " + A.marks[hitMile].mile);
          hitMile++;
        }
        while (hitWater < waters.length && d >= waters[hitWater].d) {
          var wel = waterEls[hitWater];
          wel.classList.add("hit");
          (function (x) { setTimeout(function () { x.classList.remove("hit"); }, 2200); })(wel);
          toast("💧 Water station");
          hitWater++;
        }
        var lap = A.loop[p.i] || 1;
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
    dist(A.meters);
    mileEls.forEach(function (el) { el.classList.add("done"); });
    // Side room for the Start/Finish flags, which lean outward past the course itself.
    var cam = map.cameraForBounds(bounds(), { padding: { top: 110, bottom: 150, left: 85, right: 85 } });
    map.flyTo({ center: cam.center, zoom: cam.zoom - (celebrate ? 0.25 : 0), bearing: 0, pitch: celebrate ? 30 : 0,
                padding: { top: 0, bottom: 0, left: 0, right: 0 },
                duration: celebrate ? OUTRO_MS : 0, essential: true });
    if (celebrate) timer = setTimeout(finishBurst, OUTRO_MS + 60);   // once the camera has settled
  }

  function stopHere() {             // the viewer grabbed the map: finish the line, keep their view
    halt();
    setRoute(null);
    dist(A.meters);
    mileEls.forEach(function (el) { el.classList.add("done"); });
  }

  function halt() {
    running = false;
    cancelAnimationFrame(raf);
    clearTimeout(timer);
    if (head) { head.remove(); head = null; }
    if (A) { setTrail(null); elevDot(null); }
    $("cv-skip").hidden = true;
    $("cv-replay").hidden = false;
  }

  var shoot = window.confetti ? window.confetti.create($("cv-confetti"), { resize: true, useWorker: false }) : null;
  // The finish line explodes: a burst out of the 🏁 flag in every direction, a second
  // pop straight up a beat later, and it all rains back down around the line.
  function finishBurst() {
    if (!shoot || reduce || !A) return;
    var colors = ["#ffd400", "#ff7a00", "#ff2d95", "#22d3ee", "#7CFC00", "#ffffff"];
    var pt = map.project(A.finish);
    var o = { x: Math.min(0.95, Math.max(0.05, pt.x / window.innerWidth)),
              y: Math.min(0.9, Math.max(0.1, (pt.y - 14) / window.innerHeight)) };   // from the flag, not under it
    shoot({ particleCount: 160, spread: 360, startVelocity: 32, gravity: 0.8, ticks: 260,
            decay: 0.91, scalar: 1.05, colors: colors, origin: o });
    setTimeout(function () {
      shoot({ particleCount: 90, angle: 90, spread: 70, startVelocity: 45, gravity: 0.9, ticks: 280,
              scalar: 1.1, colors: colors, origin: o });
    }, 250);
    setTimeout(function () {
      shoot({ particleCount: 60, spread: 360, startVelocity: 22, gravity: 0.7, ticks: 220,
              scalar: 0.9, shapes: ["circle"], colors: colors, origin: o });
    }, 550);
  }

  $("cv-skip").onclick = function () { overview(false); };
  $("cv-replay").onclick = function () { flyover(); };
})();
