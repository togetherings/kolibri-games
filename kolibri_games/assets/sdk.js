/* Kolibri Games SDK, API version 1.
 *
 * Include it in your game's HTML with:
 *   <script src="__kolibri_games__/sdk.js"></script>
 * (relative to your game's root; Kolibri Games always serves the current SDK
 * at that path, so you don't need to ship a copy).
 *
 * Every call returns a Promise. See docs/GAME_FORMAT.md for details.
 *
 *   KolibriGames.ready()                -> {game, player, settings, rules, summary, preview}
 *   KolibriGames.start({resume: true})  -> {attempt, public, resumed, time_limit, elapsed}
 *   KolibriGames.event(type, data)      -> reply from the game's rule checker (or {})
 *   KolibriGames.finish({score, detail})-> {attempt, standing, counts}
 *   KolibriGames.abandon()
 *   KolibriGames.scoreboard()           -> {rows, visibility, counts}
 *   KolibriGames.myResults()            -> {attempts}
 *   KolibriGames.getState() / setState(data)   saved data for this player (max 64 KB)
 *   KolibriGames.call(method, params)   ask the game's rule checker something
 *   KolibriGames.exit()                 go back to the games list
 *   KolibriGames.on("timeup", fn)       events from the platform
 *
 * Opened outside Kolibri Games (e.g. straight from a folder or in Kiwix), the
 * SDK runs in *preview mode*: results are kept in this browser only and games
 * that need a rule checker can't be played.
 */
(function () {
  "use strict";
  if (window.KolibriGames) return;

  var API = 1;
  var TIMEOUT_MS = 20000;
  var embedded = window.parent !== window;
  var pending = {};
  var nextId = 1;
  var handlers = {};

  function makeError(code, message) {
    var err = new Error(message);
    err.code = code;
    return err;
  }

  function emit(name, data) {
    (handlers[name] || []).forEach(function (fn) {
      try { fn(data); } catch (e) { console.error(e); }
    });
  }

  // ------------------------------------------------------------ embedded

  function send(method, params) {
    return new Promise(function (resolve, reject) {
      var id = nextId++;
      var timer = setTimeout(function () {
        delete pending[id];
        reject(makeError("timeout", "The game lost contact with Kolibri. Check your connection and try again."));
      }, TIMEOUT_MS);
      pending[id] = { resolve: resolve, reject: reject, timer: timer };
      window.parent.postMessage({ kg: API, id: id, method: method, params: params || {} }, "*");
    });
  }

  window.addEventListener("message", function (e) {
    if (e.source !== window.parent) return;
    var msg = e.data;
    if (!msg || msg.kg !== API) return;
    if (typeof msg.id === "number" && pending[msg.id]) {
      var p = pending[msg.id];
      delete pending[msg.id];
      clearTimeout(p.timer);
      if (msg.error) p.reject(makeError(msg.error.code, msg.error.message));
      else p.resolve(msg.result);
      if (msg.error && msg.error.code === "time_up") emit("timeup", {});
    } else if (typeof msg.event === "string") {
      emit(msg.event, msg.data || {});
    }
  });

  // ------------------------------------------------------------- preview

  var preview = (function () {
    var store = {};
    function load(key, fallback) {
      try { var v = localStorage.getItem("kolibri-games-preview:" + key); return v ? JSON.parse(v) : fallback; }
      catch (e) { return key in store ? store[key] : fallback; }
    }
    function save(key, value) {
      store[key] = value;
      try { localStorage.setItem("kolibri-games-preview:" + key, JSON.stringify(value)); } catch (e) { /* private mode */ }
    }
    var manifest = null;
    var attempt = null;
    function getManifest() {
      if (manifest) return Promise.resolve(manifest);
      return fetch("kolibri-game.json").then(function (r) { return r.json(); }).then(function (m) {
        manifest = m;
        return m;
      }).catch(function () {
        manifest = { id: "preview", title: document.title || "Game", settings: [] };
        return manifest;
      });
    }
    function settingsOf(m) {
      var s = {};
      (m.settings || []).forEach(function (f) { s[f.key] = f["default"]; });
      return s;
    }
    function needsServer(m) {
      if (m.validator) {
        throw makeError("needs_kolibri", "This game needs Kolibri Games to play, because its rule checker runs on the server.");
      }
    }
    return {
      hello: function () {
        return getManifest().then(function (m) {
          var results = load(m.id + ":results", []);
          return {
            game: { id: m.id, title: m.title, version: m.version, scoring: m.scoring || null, validator: m.validator || null },
            player: { name: "Preview player", role: "learner" },
            platform: { version: "preview", api: API },
            settings: settingsOf(m),
            rules: { counts: (m.scoring && m.scoring.counts) || "first", scoreboard: "names", time_limit: null },
            summary: { attempts: results.length, counted: null, counts: "best", first_used: results.length > 0 },
            preview: true
          };
        });
      },
      "attempt.start": function () {
        return getManifest().then(function (m) {
          needsServer(m);
          attempt = { id: Date.now(), number: load(m.id + ":results", []).length + 1, started: Date.now(), events: [] };
          return { attempt: { id: attempt.id, number: attempt.number, status: "started", practice: false }, public: {}, resumed: false, time_limit: null, elapsed: 0 };
        });
      },
      "attempt.event": function (p) {
        if (!attempt) return Promise.reject(makeError("no_attempt", "Start the game first."));
        attempt.events.push({ type: p.type, data: p.data });
        return Promise.resolve({});
      },
      "attempt.finish": function (p) {
        if (!attempt) return Promise.reject(makeError("no_attempt", "Start the game first."));
        return getManifest().then(function (m) {
          var seconds = (Date.now() - attempt.started) / 1000;
          var results = load(m.id + ":results", []);
          results.push({ score: p.score, seconds: seconds });
          save(m.id + ":results", results);
          var a = { id: attempt.id, number: attempt.number, status: "finished", practice: false, score: p.score, seconds: Math.round(seconds * 10) / 10, verified: false };
          attempt = null;
          return { attempt: a, standing: null, counts: "best" };
        });
      },
      "attempt.abandon": function () { attempt = null; return Promise.resolve({ ok: true }); },
      "scoreboard.get": function () { return Promise.resolve({ rows: [], visibility: "names", counts: "best" }); },
      "results.mine": function () {
        return getManifest().then(function (m) {
          return { attempts: load(m.id + ":results", []).map(function (r, i) {
            return { number: i + 1, status: "finished", score: r.score, seconds: r.seconds, practice: false, verified: false };
          }) };
        });
      },
      "state.get": function () { return getManifest().then(function (m) { return load(m.id + ":state", null); }); },
      "state.set": function (p) { return getManifest().then(function (m) { save(m.id + ":state", p.data); return { ok: true }; }); },
      call: function () { return Promise.reject(makeError("needs_kolibri", "This needs Kolibri Games.")); },
      exit: function () { return Promise.resolve({ ok: true }); }
    };
  })();

  function request(method, params) {
    if (embedded) return send(method, params);
    try {
      return Promise.resolve(preview[method](params || {}));
    } catch (e) {
      return Promise.reject(e);
    }
  }

  window.KolibriGames = {
    apiVersion: API,
    preview: !embedded,
    ready: function () { return request("hello"); },
    start: function (opts) { return request("attempt.start", { resume: !opts || opts.resume !== false }); },
    event: function (type, data) { return request("attempt.event", { type: type, data: data === undefined ? null : data }); },
    finish: function (result) {
      result = result || {};
      return request("attempt.finish", { score: result.score === undefined ? null : result.score, detail: result.detail || {} });
    },
    abandon: function () { return request("attempt.abandon"); },
    scoreboard: function () { return request("scoreboard.get"); },
    myResults: function () { return request("results.mine"); },
    getState: function () { return request("state.get"); },
    setState: function (data) { return request("state.set", { data: data }); },
    call: function (method, params) { return request("call", { method: method, params: params || {} }); },
    exit: function () { return request("exit"); },
    on: function (name, fn) { (handlers[name] = handlers[name] || []).push(fn); }
  };
})();
