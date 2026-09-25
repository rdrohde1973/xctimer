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
  // a cross-country course, and it lets the spline work in real distances.
  function projector(origin) {
    var kx = Math.cos(origin[1] * RAD) * R * RAD, ky = R * RAD;
    return {
      fwd: function (p) { return [(p[0] - origin[0]) * kx, (p[1] - origin[1]) * ky]; },
      inv: function (q) { return [origin[0] + q[0] / kx, origin[1] + q[1] / ky]; }
    };
  }

  /* Smooth the route with a CENTRIPETAL Catmull-Rom spline. It passes through every point
   * the host clicked -- a smoothed course still goes round the same trees -- and, unlike
   * the plain version, never overshoots into little loops on sharp turns. */
  // A double-click drops two points on one spot; a zero-length segment would divide by
  // zero in the spline and turn the whole line into NaN.
  function dedupe(pts) {
    var out = [];
    for (var i = 0; i < (pts || []).length; i++) {
      if (!out.length || hav(out[out.length - 1], pts[i]) > 0.5) out.push(pts[i]);
    }
    return out;
  }

  function smooth(pts, spacing) {
    pts = dedupe(pts);
    if (pts.length < 3) return pts.slice();
    spacing = spacing || 4;
    var pr = projector(pts[0]);
    var P = pts.map(pr.fwd);
    var ext = [[2 * P[0][0] - P[1][0], 2 * P[0][1] - P[1][1]]].concat(P,
      [[2 * P[P.length - 1][0] - P[P.length - 2][0], 2 * P[P.length - 1][1] - P[P.length - 2][1]]]);
    var out = [pts[0]];
    for (var i = 1; i < ext.length - 2; i++) {
      var p0 = ext[i - 1], p1 = ext[i], p2 = ext[i + 1], p3 = ext[i + 2];
      var seg = Math.hypot(p2[0] - p1[0], p2[1] - p1[1]);
      var n = Math.max(2, Math.min(60, Math.round(seg / spacing)));
      var t0 = 0, t1 = t0 + Math.pow(Math.hypot(p1[0] - p0[0], p1[1] - p0[1]), 0.5) || 1e-6;
      var t2 = t1 + Math.pow(seg, 0.5) || t1 + 1e-6;
      var t3 = t2 + Math.pow(Math.hypot(p3[0] - p2[0], p3[1] - p2[1]), 0.5) || t2 + 1e-6;
      for (var k = 1; k <= n; k++) {
        var t = t1 + (t2 - t1) * k / n;
        var q = [0, 0];
        for (var c = 0; c < 2; c++) {
          var A1 = (t1 - t) / (t1 - t0) * p0[c] + (t - t0) / (t1 - t0) * p1[c];
          var A2 = (t2 - t) / (t2 - t1) * p1[c] + (t - t1) / (t2 - t1) * p2[c];
          var A3 = (t3 - t) / (t3 - t2) * p2[c] + (t - t2) / (t3 - t2) * p3[c];
          var B1 = (t2 - t) / (t2 - t0) * A1 + (t - t0) / (t2 - t0) * A2;
          var B2 = (t3 - t) / (t3 - t1) * A2 + (t - t1) / (t3 - t1) * A3;
          q[c] = (t2 - t) / (t2 - t1) * B1 + (t - t1) / (t2 - t1) * B2;
        }
        out.push(k === n ? pts[i] : pr.inv(q));   // land exactly on the clicked point
      }
    }
    return out;
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

  /* Which lap of the ground under each sample is this? 1 = first time over it, 2 = the
   * second time (a repeat loop), and so on. A sample counts the separate earlier visits
   * within RADIUS metres, ignoring the stretch just behind it. Short brushes -- crossing
   * an earlier path, a start line near the finish chute -- are shorter than MIN_RUN and
   * don't count as a new loop. */
  function passes(samples, radius, minRun) {
    // 25 m: a lap drawn by hand lands within a few metres of the first on a zoomed-in map,
    // but can drift 15-20 m when the host clicks from further out.
    radius = radius || 25;
    minRun = minRun || 80;
    var gap = 150, n = samples.length, raw = new Array(n);
    var pr = n ? projector(samples[0].p) : null;
    var xy = samples.map(function (s) { return pr.fwd(s.p); });
    for (var i = 0; i < n; i++) {
      var visits = 0, lastHit = -1e9;
      for (var j = 0; j < i; j++) {
        if (samples[j].d > samples[i].d - gap) break;
        if (Math.hypot(xy[i][0] - xy[j][0], xy[i][1] - xy[j][1]) <= radius) {
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

  /* Split a route into runs of the same lap, for colouring:
   * [{pass:1, coords:[[lng,lat],...], d0, d1}, ...]. Runs share their joining point so
   * the drawn line has no gaps. Optional `upto` cuts the route at that distance (the
   * fly-over draws it progressively). */
  function runs(samples, laps, upto) {
    var out = [], cur = null;
    for (var i = 0; i < samples.length; i++) {
      var s = samples[i];
      if (upto != null && s.d > upto) {
        if (cur && i > 0) cur.coords.push(pointAt(samples, upto).p);
        break;
      }
      if (!cur || laps[i] !== cur.pass) {
        var join = cur ? cur.coords[cur.coords.length - 1] : null;
        cur = { pass: laps[i], coords: join ? [join] : [], d0: s.d, d1: s.d };
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
    var loops = laps.reduce(function (m, x) { return Math.max(m, x); }, 0);
    return {
      path: path, samples: samples, laps: laps, loops: loops,
      meters: samples.length ? samples[samples.length - 1].d : 0,
      miles: (samples.length ? samples[samples.length - 1].d : 0) / MILE,
      marks: mileMarks(samples),
      start: path[0] || null, finish: path[path.length - 1] || null
    };
  }

  var LAP_COLORS = ["#ffd400", "#ff7a00", "#ff2d95", "#9b5cff", "#22d3ee", "#7CFC00"];
  function lapColor(n) { return LAP_COLORS[(Math.max(1, n) - 1) % LAP_COLORS.length]; }

  var api = { hav: hav, length: length, dedupe: dedupe, smooth: smooth, resample: resample, passes: passes,
              pointAt: pointAt, bearing: bearing, mileMarks: mileMarks, runs: runs,
              analyse: analyse, lapColor: lapColor, MILE: MILE };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.CourseGeo = api;
})(this);
