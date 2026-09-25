/* XCTimer course maps — geometry shared by the editor and the results-page viewer.
 *
 * Points are [lng, lat]. Everything is computed from the clicked points on the fly, so
 * the database stores only what the host plotted and the two pages can never disagree.
 * Plain browser global (window.CourseGeo) and a CommonJS export, so node can test it.
 */
(function (root) {
  "use strict";
  var R = 6371008.8;               // mean Earth radius, metres
  var MILE = 1609.344;
  var RAD = Math.PI / 180;

  function hav(a, b) {
    var dLat = (b[1] - a[1]) * RAD, dLng = (b[0] - a[0]) * RAD;
    var s = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
            Math.cos(a[1] * RAD) * Math.cos(b[1] * RAD) * Math.sin(dLng / 2) * Math.sin(dLng / 2);
    return 2 * R * Math.asin(Math.min(1, Math.sqrt(s)));
  }

  function length(pts) {
    var d = 0;
    for (var i = 1; i < pts.length; i++) d += hav(pts[i - 1], pts[i]);
    return d;
  }

  // Local flat projection around a point: metres east/north. Good to well under 1% over
  // a cross-country course, and it lets corner rounding work in real distances.
  function projector(origin) {
    var kx = Math.cos(origin[1] * RAD) * R * RAD, ky = R * RAD;
    return {
      fwd: function (p) { return [(p[0] - origin[0]) * kx, (p[1] - origin[1]) * ky]; },
      inv: function (q) { return [origin[0] + q[0] / kx, origin[1] + q[1] / ky]; }
    };
  }

  // A double-click drops two points on one spot; a zero-length segment would divide by
  // zero when rounding its corner and turn the line into NaN.
  function dedupe(pts) {
    var out = [];
    for (var i = 0; i < (pts || []).length; i++) {
      if (!out.length || hav(out[out.length - 1], pts[i]) > 0.5) out.push(pts[i]);
    }
    return out;
  }

  /* "Smooth" = keep the host's straight lines and just round off each corner. Each corner
   * gets a small curve (at most ROUND metres back along either leg, never more than half a
   * leg) that stays inside the corner, so the line can't swing out across a street the way
   * a spline fitted through the points did -- it never strays more than a few metres. */
  var ROUND = 10;
  function smooth(pts, spacing) {
    pts = dedupe(pts);
    if (pts.length < 3) return pts.slice();
    spacing = spacing || 2;
    var pr = projector(pts[0]);
    var P = pts.map(pr.fwd);
    var out = [pts[0]];
    for (var i = 1; i < P.length - 1; i++) {
      var a = P[i - 1], p = P[i], b = P[i + 1];
      var la = Math.hypot(a[0] - p[0], a[1] - p[1]), lb = Math.hypot(b[0] - p[0], b[1] - p[1]);
      var r = Math.min(ROUND, la / 2, lb / 2);
      var s = [p[0] + (a[0] - p[0]) * r / la, p[1] + (a[1] - p[1]) * r / la];   // curve start, on leg in
      var e = [p[0] + (b[0] - p[0]) * r / lb, p[1] + (b[1] - p[1]) * r / lb];   // curve end, on leg out
      var n = Math.max(2, Math.min(24, Math.round(2 * r / spacing)));
      for (var k = 0; k <= n; k++) {               // quadratic Bezier with the corner as control
        var t = k / n, u = 1 - t;
        out.push(pr.inv([u * u * s[0] + 2 * u * t * p[0] + t * t * e[0],
                         u * u * s[1] + 2 * u * t * p[1] + t * t * e[1]]));
      }
    }
    out.push(pts[pts.length - 1]);
    return dedupe(out);
  }

  /* Evenly spaced samples along a path: [{p:[lng,lat], d:metres from start}]. */
  function resample(path, step) {
    step = step || 5;
    if (!path || path.length < 2) return path && path.length ? [{ p: path[0], d: 0 }] : [];
    var out = [{ p: path[0], d: 0 }], total = 0, next = step;
    for (var i = 1; i < path.length; i++) {
      var a = path[i - 1], b = path[i], seg = hav(a, b);
      while (seg > 0 && next <= total + seg) {
        var f = (next - total) / seg;
        out.push({ p: [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f], d: next });
        next += step;
      }
      total += seg;
    }
    var last = path[path.length - 1];
    if (total - out[out.length - 1].d > 0.01) out.push({ p: last, d: total });
    return out;
  }

  // Closest point to p on the segment a-b (flat x/y metres), and the distance to it.
  function nearestOnSeg(p, a, b) {
    var ux = b[0] - a[0], uy = b[1] - a[1], L = ux * ux + uy * uy;
    var t = L ? Math.max(0, Math.min(1, ((p[0] - a[0]) * ux + (p[1] - a[1]) * uy) / L)) : 0;
    return [a[0] + ux * t, a[1] + uy * t];
  }
  function segDist(p, a, b) { var q = nearestOnSeg(p, a, b); return Math.hypot(p[0] - q[0], p[1] - q[1]); }

  /* Which lap of the ground under each sample is this? 1 = first time over it, 2 = the
   * second time (a repeat loop), and so on. A sample counts the separate earlier visits
   * of the route within RADIUS metres of it, ignoring the stretch just behind it. Short brushes -- crossing
   * an earlier path, a start line near the finish chute -- are shorter than MIN_RUN and
   * don't count as a new loop. */
  function passes(samples, radius, minRun) {
    // 4 m: a repeat loop is plotted by clicking the earlier loop's dots, so it lies right on
    // top of it. Anything further off is the host deliberately going somewhere new -- e.g.
    // breaking off the last lap for the finish -- and is new ground, not a repeat.
    radius = radius || 4;
    minRun = minRun || 80;
    var gap = 150, n = samples.length, raw = new Array(n);
    var pr = n ? projector(samples[0].p) : null;
    var xy = samples.map(function (s) { return pr.fwd(s.p); });
    for (var i = 0; i < n; i++) {
      var visits = 0, lastHit = -1e9;
      for (var j = 0; j + 1 < i; j++) {
        if (samples[j + 1].d > samples[i].d - gap) break;
        if (segDist(xy[i], xy[j], xy[j + 1]) <= radius) {
          if (samples[j].d - lastHit > gap) visits++;
          lastHit = samples[j].d;
        }
      }
      raw[i] = visits + 1;
    }
    // Hysteresis: a change of lap must last MIN_RUN metres, or it was just a brush.
    var out = raw.slice(), start = 0;
    for (var k = 1; k <= n; k++) {
      if (k === n || raw[k] !== raw[start]) {
        var runLen = samples[k - 1].d - samples[start].d;
        if (start > 0 && runLen < minRun) {
          for (var m = start; m < k; m++) out[m] = out[start - 1];
        }
        start = k;
      }
    }
    return out;
  }

  /* Pull repeat-pass samples that are within SNAP (2 m) of an earlier stretch of the route
   * right onto it, so loop 2 draws exactly on top of loop 1. Anything further off is drawn
   * exactly where it was clicked -- the host can always break away from an old loop.
   * Distances stay as plotted; only the drawing moves. */
  function follow(samples, laps, snap, radius) {
    snap = snap || 2;
    radius = radius || 2.5;
    var gap = 150, n = samples.length;
    if (n < 3) return samples;
    var pr = projector(samples[0].p);
    var xy = samples.map(function (s) { return pr.fwd(s.p); });
    var out = samples.map(function (s) { return { p: s.p, d: s.d }; });
    for (var i = 0; i < n; i++) {
      if ((laps[i] || 1) < 2) continue;
      var best = Infinity, bx = 0, by = 0;
      for (var j = 0; j + 1 < n; j++) {
        if (samples[j + 1].d > samples[i].d - gap) break;
        var q = nearestOnSeg(xy[i], xy[j], xy[j + 1]);
        var dd = Math.hypot(xy[i][0] - q[0], xy[i][1] - q[1]);
        if (dd < best) { best = dd; bx = q[0]; by = q[1]; }
      }
      if (best > radius) continue;
      var w = best <= snap ? 1 : (radius - best) / (radius - snap);
      xy[i] = [xy[i][0] + (bx - xy[i][0]) * w, xy[i][1] + (by - xy[i][1]) * w];
      out[i].p = pr.inv(xy[i]);        // later loops then follow this one, i.e. loop 1
    }
    return out;
  }

  /* Position and heading at a distance along the samples. */
  function pointAt(samples, d) {
    if (!samples.length) return null;
    if (d <= 0) return { p: samples[0].p, i: 0 };
    var last = samples[samples.length - 1];
    if (d >= last.d) return { p: last.p, i: samples.length - 1 };
    var lo = 0, hi = samples.length - 1;
    while (hi - lo > 1) { var mid = (lo + hi) >> 1; if (samples[mid].d <= d) lo = mid; else hi = mid; }
    var a = samples[lo], b = samples[hi], f = (d - a.d) / ((b.d - a.d) || 1);
    return { p: [a.p[0] + (b.p[0] - a.p[0]) * f, a.p[1] + (b.p[1] - a.p[1]) * f], i: lo };
  }

  function bearing(a, b) {
    var y = Math.sin((b[0] - a[0]) * RAD) * Math.cos(b[1] * RAD);
    var x = Math.cos(a[1] * RAD) * Math.sin(b[1] * RAD) -
            Math.sin(a[1] * RAD) * Math.cos(b[1] * RAD) * Math.cos((b[0] - a[0]) * RAD);
    return (Math.atan2(y, x) / RAD + 360) % 360;
  }

  /* Every whole mile along the route: [{mile:1, p:[lng,lat], d:1609.3}, ...]. */
  function mileMarks(samples) {
    var out = [], total = samples.length ? samples[samples.length - 1].d : 0;
    for (var m = 1; m * MILE < total - 1; m++) {
      out.push({ mile: m, p: pointAt(samples, m * MILE).p, d: m * MILE });
    }
    return out;
  }

  /* Split a route into runs for drawing:
   * [{pass:2, loop:2, coords:[[lng,lat],...], d0, d1}, ...].
   *   pass -- how many times this ground has been covered (sets the stripe width: a repeat
   *           loop is a narrower stripe down the middle of the one under it)
   *   loop -- which loop the runner is on (sets the colour; never goes back down, so the
   *           run to the finish after loop 2 stays loop 2's colour even on new ground)
   * Runs share their joining point so the drawn line has no gaps. Optional `upto` cuts
   * the route at that distance (the fly-over draws it progressively). */
  function runs(samples, laps, upto, loop) {
    loop = loop || laps;
    var out = [], cur = null;
    for (var i = 0; i < samples.length; i++) {
      var s = samples[i];
      if (upto != null && s.d > upto) {
        if (cur && i > 0) cur.coords.push(pointAt(samples, upto).p);
        break;
      }
      if (!cur || laps[i] !== cur.pass || loop[i] !== cur.loop) {
        var join = cur ? cur.coords[cur.coords.length - 1] : null;
        cur = { pass: laps[i], loop: loop[i], coords: join ? [join] : [], d0: s.d, d1: s.d };
        out.push(cur);
      }
      cur.coords.push(s.p);
      cur.d1 = s.d;
    }
    return out.filter(function (r) { return r.coords.length >= 2; });
  }

  /* Everything a page needs about one course, from the raw clicked points. */
  function analyse(points, doSmooth) {
    var path = doSmooth ? smooth(points) : dedupe(points);
    var samples = resample(path, 5);
    var laps = samples.length ? passes(samples) : [];
    samples = follow(samples, laps);
    var loops = laps.reduce(function (m, x) { return Math.max(m, x); }, 0);
    var hi = 1, loop = laps.map(function (x) { hi = Math.max(hi, x); return hi; });   // loop the runner is on
    if (loops > 1) path = samples.map(function (s) { return s.p; });   // the line as drawn
    return {
      path: path, samples: samples, laps: laps, loop: loop, loops: loops,
      meters: samples.length ? samples[samples.length - 1].d : 0,
      miles: (samples.length ? samples[samples.length - 1].d : 0) / MILE,
      marks: mileMarks(samples),
      start: path[0] || null, finish: path[path.length - 1] || null
    };
  }

  // ---------------------------------------------------------------- elevation
  /* Terrarium elevation tiles (the same ones the 3D terrain uses) store metres in the
   * pixel colour: (R * 256 + G + B / 256) - 32768. */
  function terrarium(r, g, b) { return r * 256 + g + b / 256 - 32768; }

  /* Web-Mercator position of [lng, lat] in whole-world pixels at zoom z (256 px tiles). */
  function worldPx(p, z) {
    var n = 256 * Math.pow(2, z), lat = Math.max(-85, Math.min(85, p[1])) * RAD;
    return [(p[0] + 180) / 360 * n, (1 - Math.log(Math.tan(lat) + 1 / Math.cos(lat)) / Math.PI) / 2 * n];
  }

  /* The hills of a course from elevations (metres) at each sample:
   *   gain  -- total climbing, ignoring wobbles under a metre (tile noise)
   *   climb -- the biggest single climb {rise, from, to (metres along), grade}; a dip of
   *            under 3 m on the way up doesn't end it
   *   lo/hi -- lowest and highest points. */
  function hills(elev, samples) {
    var n = elev.length, out = { gain: 0, climb: null, lo: Infinity, hi: -Infinity };
    if (n < 2) return out;
    var e = elev.map(function (_, i) {          // +-15 m moving average: tiles are ~4 m pixels
      var s = 0, k = 0;
      for (var j = Math.max(0, i - 3); j <= Math.min(n - 1, i + 3); j++) { s += elev[j]; k++; }
      return s / k;
    });
    var ref = e[0];
    for (var i = 0; i < n; i++) {
      out.lo = Math.min(out.lo, e[i]); out.hi = Math.max(out.hi, e[i]);
      if (e[i] > ref + 1) { out.gain += e[i] - ref; ref = e[i]; }
      else if (e[i] < ref - 1) ref = e[i];
    }
    var lo = 0, pk = 0;
    function take() {
      var rise = e[pk] - e[lo];
      if (pk > lo && (!out.climb || rise > out.climb.rise)) {
        var run = samples[pk].d - samples[lo].d;
        out.climb = { rise: rise, from: samples[lo].d, to: samples[pk].d, grade: run ? rise / run : 0 };
      }
    }
    for (var t = 1; t < n; t++) {
      if (e[t] > e[pk]) pk = t;
      if (e[pk] - e[t] > 3) { take(); lo = pk = t; }
      else if (e[t] <= e[lo]) { lo = pk = t; }    // still level or lower: the climb hasn't begun
    }
    take();
    return out;
  }

  /* How far along the route (metres) a spot is: the nearest sample's distance. */
  function along(samples, p) {
    var best = Infinity, d = 0;
    for (var i = 0; i < samples.length; i++) {
      var h = hav(samples[i].p, p);
      if (h < best) { best = h; d = samples[i].d; }
    }
    return { d: d, off: best };
  }

  // Blue, orange, purple (then deeper shades of each): every loop's stripe stands out
  // against the loop underneath it -- green on blue didn't -- and reads over grass and trees.
  var LAP_COLORS = ["#38bdf8", "#ff6a00", "#a855f7", "#2563eb", "#c2410c", "#e879f9"];
  function lapColor(n) { return LAP_COLORS[(Math.max(1, n) - 1) % LAP_COLORS.length]; }
  // Repeat loops ride on the same line, each a narrower stripe down the middle of the one
  // before, so every loop's colour still shows without drawing a second trail beside it.
  // Each loop is half the width of the one under it, so a good edge of the loop below
  // shows on both sides (at 0.55 it was hard to see).
  function lapWidth(n, base) { return Math.max(1.5, base * Math.pow(0.5, Math.max(1, n) - 1)); }

  var api = { hav: hav, length: length, dedupe: dedupe, smooth: smooth, resample: resample, passes: passes,
              pointAt: pointAt, bearing: bearing, mileMarks: mileMarks, runs: runs, follow: follow,
              analyse: analyse, lapColor: lapColor, lapWidth: lapWidth, MILE: MILE,
              terrarium: terrarium, worldPx: worldPx, hills: hills, along: along };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.CourseGeo = api;
})(this);
