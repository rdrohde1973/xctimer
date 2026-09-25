/* XCTimer course map editor: click to plot, drag to adjust, smooth, save. */
(function () {
  "use strict";
  var CFG = JSON.parse(document.getElementById("cm-config").textContent);
  var G = window.CourseGeo;
  var $ = function (id) { return document.getElementById(id); };
  maplibregl.setWorkerUrl(CFG.worker);

  var doc = (CFG.data && Array.isArray(CFG.data.courses) && CFG.data.courses.length)
    ? CFG.data : { version: 1, courses: [{ name: "Course", points: [], smooth: false }], view: null };
  var cur = 0, sel = -1, dirty = false, ready = false;
  var ptMarkers = [], deco = [], history = [], justDragged = false;

  function course() { return doc.courses[cur]; }
  function fc(f) { return { type: "FeatureCollection", features: f }; }
  function r7(x) { return Math.round(x * 1e7) / 1e7; }
  function line(c, props) { return { type: "Feature", properties: props || {}, geometry: { type: "LineString", coordinates: c } }; }

  var lineLayout = { "line-join": "round", "line-cap": "round" };
  var map;
  try {
    map = new maplibregl.Map({
      container: "cm-map",
      style: {
        version: 8,
        sources: {
          sat: { type: "raster", tiles: [CFG.tiles.url], tileSize: 256, maxzoom: CFG.tiles.maxzoom,
                 attribution: CFG.tiles.attribution },
          route: { type: "geojson", data: fc([]) },
          raw: { type: "geojson", data: fc([]) }
        },
        layers: [
          { id: "sat", type: "raster", source: "sat" },
          { id: "raw", type: "line", source: "raw", layout: lineLayout,
            paint: { "line-color": "#ffffff", "line-width": 1.5, "line-opacity": 0.75, "line-dasharray": [2, 2] } },
          { id: "route-casing", type: "line", source: "route", layout: lineLayout,
            paint: { "line-color": "#0a1728", "line-width": 7, "line-opacity": 0.55, "line-offset": ["get", "offset"] } },
          { id: "route", type: "line", source: "route", layout: lineLayout,
            paint: { "line-color": ["get", "color"], "line-width": 4, "line-offset": ["get", "offset"] } }
        ]
      },
      center: doc.view ? doc.view.center : [-98.5, 39.8],
      zoom: doc.view ? doc.view.zoom : 3.5,
      maxZoom: 20, doubleClickZoom: false, attributionControl: { compact: true }
    });
  } catch (e) {
    $("cm-map").innerHTML = '<div class="card muted" style="margin:1rem">This browser can\'t draw the map (WebGL is off or unavailable).</div>';
    return;
  }
  map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-right");
  map.addControl(new maplibregl.ScaleControl({ unit: "imperial" }), "bottom-left");
  map.on("load", function () {
    ready = true;
    render();
    if (!doc.view && course().points.length > 1) fit();
    if (!doc.view && !course().points.length) $("cm-q").focus();
  });

  // ---------------------------------------------------------------- plotting
  map.on("click", function (e) {
    if (justDragged) return;
    snapshot();
    course().points.push([r7(e.lngLat.lng), r7(e.lngLat.lat)]);
    sel = -1;
    changed();
  });
  map.on("mousemove", function (e) {
    var pts = course().points, el = $("cm-live");
    if (!el) return;
    if (!pts.length) { el.textContent = ""; return; }
    var a = G.analyse(pts, false);
    var add = G.hav(pts[pts.length - 1], [e.lngLat.lng, e.lngLat.lat]);
    el.textContent = "Next point here: " + ((a.meters + add) / G.MILE).toFixed(2) + " mi (+" + Math.round(add) + " m)";
  });

  function drawPoints() {
    ptMarkers.forEach(function (m) { m.remove(); });
    ptMarkers = course().points.map(function (p, i) {
      var el = document.createElement("div");
      el.className = "cm-pt" + (i === sel ? " sel" : "");
      el.title = "Point " + (i + 1) + " — drag to move, click to select";
      el.addEventListener("click", function (ev) {
        ev.stopPropagation();
        if (justDragged) return;
        sel = (sel === i ? -1 : i);
        drawPoints();
        buttons();
      });
      var mk = new maplibregl.Marker({ element: el, draggable: true }).setLngLat(p).addTo(map);
      mk.on("dragstart", function () { snapshot(); justDragged = true; });
      mk.on("dragend", function () {
        var ll = mk.getLngLat();
        course().points[i] = [r7(ll.lng), r7(ll.lat)];
        sel = i;
        changed();
        setTimeout(function () { justDragged = false; }, 50);   // swallow the click after a drag
      });
      return mk;
    });
  }

  function flag(cls, icon, text) {
    var el = document.createElement("div");
    el.className = "cflag " + cls;
    el.innerHTML = '<span class="fi">' + icon + "</span>" + text;
    return el;
  }

  function drawDeco(a) {
    deco.forEach(function (m) { m.remove(); });
    deco = [];
    if (course().points.length < 2) return;
    // Mile marks first: markers added later draw on top, and the flags matter more.
    a.marks.forEach(function (mk) {
      var el = document.createElement("div");
      el.className = "cmile";
      el.textContent = mk.mile + " mi";
      deco.push(new maplibregl.Marker({ element: el }).setLngLat(mk.p).addTo(map));
    });
    if (G.hav(a.start, a.finish) < 25) {
      deco.push(new maplibregl.Marker({ element: flag("finish", "🏁", "Start / Finish"), anchor: "bottom" }).setLngLat(a.start).addTo(map));
    } else {
      // Close together (a finish chute beside the start line), the two flags would sit on
      // top of each other -- lean them apart instead.
      var near = G.hav(a.start, a.finish) < 120, west = a.start[0] < a.finish[0];
      deco.push(new maplibregl.Marker({ element: flag("start", "🟢", "Start"),
        anchor: near ? (west ? "bottom-right" : "bottom-left") : "bottom" }).setLngLat(a.start).addTo(map));
      deco.push(new maplibregl.Marker({ element: flag("finish", "🏁", "Finish"),
        anchor: near ? (west ? "bottom-left" : "bottom-right") : "bottom" }).setLngLat(a.finish).addTo(map));
    }
  }

  function legend(n) {
    var h = '<span class="cm-legend">';
    for (var i = 1; i <= n; i++) h += '<span><i style="background:' + G.lapColor(i) + '"></i>Loop ' + i + "</span>";
    return h + "</span>";
  }

  function render() {
    if (!ready) return;
    var c = course(), a = G.analyse(c.points, c.smooth);
    var runs = G.runs(a.samples, a.laps);
    map.getSource("route").setData(fc(runs.map(function (r) {
      // Each repeat loop gets its own colour AND sits a lane to the side, so laps drawn
      // over the same ground stay visible instead of the last one hiding the rest.
      return line(r.coords, { color: G.lapColor(r.pass), offset: (r.pass - 1) * 5 });
    })));
    map.getSource("raw").setData(fc(c.smooth && c.points.length > 1 ? [line(c.points)] : []));
    drawPoints();
    drawDeco(a);
    $("cm-stats").innerHTML = c.points.length < 2
      ? '<span class="muted">Find the course, then click the map at the start line to begin.</span><span class="muted" id="cm-live"></span>'
      : '<span><b>' + a.miles.toFixed(2) + '</b> mi</span><span><b>' + (a.meters / 1000).toFixed(2) + "</b> km</span>" +
        "<span>" + c.points.length + " points</span>" + (a.loops > 1 ? legend(a.loops) : "") +
        (dirty ? '<span class="muted">· unsaved</span>' : "") + '<span class="muted" id="cm-live"></span>';
    buttons();
  }

  function buttons() {
    var c = course();
    $("cm-delpt").disabled = sel < 0;
    $("cm-repeat").disabled = !(sel >= 0 && sel < c.points.length - 2);
    $("cm-undo").disabled = !history.length;
    $("cm-clear").disabled = !c.points.length;
    $("cm-smooth").checked = !!c.smooth;
    $("cm-del").disabled = false;
    var s = $("cm-course");
    s.innerHTML = doc.courses.map(function (x, i) {
      var o = document.createElement("option");
      o.value = i; o.textContent = x.name; if (i === cur) o.selected = true;
      return o.outerHTML;
    }).join("");
  }

  function changed() { dirty = true; render(); }
  function snapshot() {
    history.push({ cur: cur, points: course().points.map(function (p) { return p.slice(); }), smooth: course().smooth });
    if (history.length > 200) history.shift();
  }
  function fit() {
    var pts = course().points;
    if (pts.length < 2) return;
    var b = new maplibregl.LngLatBounds(pts[0], pts[0]);
    pts.forEach(function (p) { b.extend(p); });
    map.fitBounds(b, { padding: 60, maxZoom: 18, duration: 600 });
  }

  // ---------------------------------------------------------------- toolbar
  $("cm-undo").onclick = function () {
    var h = history.pop();
    if (!h) return;
    cur = h.cur; doc.courses[cur].points = h.points; doc.courses[cur].smooth = h.smooth;
    sel = -1; changed();
  };
  $("cm-delpt").onclick = function () {
    if (sel < 0) return;
    snapshot(); course().points.splice(sel, 1); sel = -1; changed();
  };
  // A course that runs the same loop again: draw it once, tap the point where the loop
  // starts, Repeat. The copy lands exactly on the first lap, so its colour is always
  // detected -- and nobody has to click on top of their own points to redraw it.
  $("cm-repeat").onclick = function () {
    var pts = course().points;
    if (sel < 0 || sel >= pts.length - 2) return;
    snapshot();
    var loop = pts.slice(sel + 1).map(function (p) { return p.slice(); });
    Array.prototype.push.apply(pts, loop);
    sel = -1;
    changed();
  };
  $("cm-clear").onclick = function () {
    if (!confirm("Clear every point on \"" + course().name + "\"?")) return;
    snapshot(); course().points = []; sel = -1; changed();
  };
  $("cm-smooth").onchange = function () { snapshot(); course().smooth = this.checked; changed(); };
  $("cm-course").onchange = function () { cur = +this.value; sel = -1; render(); fit(); };
  $("cm-add").onclick = function () {
    if (doc.courses.length >= 6) { alert("Six courses is the most one meet can have."); return; }
    var name = prompt("Name for the new course (e.g. Girls 2 mile):", "Course " + (doc.courses.length + 1));
    if (name === null) return;
    doc.courses.push({ name: (name.trim() || "Course").slice(0, 60), points: [], smooth: false });
    cur = doc.courses.length - 1; sel = -1; changed();
  };
  $("cm-rename").onclick = function () {
    var name = prompt("Course name:", course().name);
    if (name === null) return;
    course().name = (name.trim() || "Course").slice(0, 60); changed();
  };
  $("cm-del").onclick = function () {
    if (!confirm("Delete the course \"" + course().name + "\"?")) return;
    if (doc.courses.length === 1) { doc.courses[0] = { name: "Course", points: [], smooth: false }; }
    else { doc.courses.splice(cur, 1); cur = 0; }
    history = []; sel = -1; changed();
  };
  $("cm-save").onclick = async function () {
    var c = map.getCenter();
    doc.view = { center: [r7(c.lng), r7(c.lat)], zoom: Math.round(map.getZoom() * 100) / 100 };
    var btn = this;
    btn.disabled = true;
    try {
      await jpost(CFG.save, doc);
      dirty = false; render();
      btn.textContent = "✓ Saved";
      setTimeout(function () { btn.textContent = "💾 Save"; }, 1800);
    } catch (e) { alert(e.message); }
    btn.disabled = false;
  };
  $("cm-preview").onclick = function (e) {
    if (dirty) { e.preventDefault(); alert("Save first — the preview shows the saved course."); }
  };
  window.addEventListener("beforeunload", function (e) { if (dirty) { e.preventDefault(); e.returnValue = ""; } });
  document.addEventListener("keydown", function (e) {
    if (/INPUT|SELECT|TEXTAREA/.test((e.target && e.target.tagName) || "")) return;
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z") { e.preventDefault(); $("cm-undo").click(); }
    else if ((e.key === "Delete" || e.key === "Backspace") && sel >= 0) { e.preventDefault(); $("cm-delpt").click(); }
  });

  // ---------------------------------------------------------------- finding the course
  $("cm-search").onsubmit = async function (ev) {
    ev.preventDefault();
    var q = $("cm-q").value.trim();
    if (!q) return;
    try {
      // OpenStreetMap Nominatim: one request per search, on submit only (their usage policy
      // rules out search-as-you-type).
      var r = await fetch("https://nominatim.openstreetmap.org/search?format=json&limit=1&q=" + encodeURIComponent(q));
      var j = await r.json();
      if (!j.length) { alert("Couldn't find that — try adding the city and state."); return; }
      var bb = j[0].boundingbox.map(Number);         // [south, north, west, east]
      map.fitBounds([[bb[2], bb[0]], [bb[3], bb[1]]], { padding: 40, maxZoom: 17, duration: 1200 });
    } catch (e) { alert("Place search isn't reachable right now — pan and zoom to the course instead."); }
  };
  $("cm-here").onclick = function () {
    if (!navigator.geolocation) { alert("This browser can't share its location."); return; }
    navigator.geolocation.getCurrentPosition(function (pos) {
      map.flyTo({ center: [pos.coords.longitude, pos.coords.latitude], zoom: 17, duration: 1200 });
    }, function () { alert("Couldn't get your location."); }, { enableHighAccuracy: true, timeout: 10000 });
  };
})();
