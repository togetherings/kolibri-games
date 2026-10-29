/* Kolibri Games: the games page.
 * Plain JavaScript with no external libraries or build step, so it works
 * offline and is easy to follow.
 *
 * Pages (the part of the address after #):
 *   #/                                  the games list
 *   #/play/<game>[/c/<challenge>]       play in free play, or in a challenge
 *   #/board/<game>[/c/<challenge>]      a scoreboard
 *   #/results/<game>[/c/<challenge>]    coaches: every learner's attempts
 *   #/challenges/<game>[/new|/edit/<id>]  coaches: set up challenges
 *   #/settings/<game>                   coaches: free-play settings
 *   #/scores/<game>[/<board>[/<class>]] Classroom Games' scoreboards
 *   #/lists[/new|/<id>]                 coaches: Wikipedia article lists
 *   #/status                            administrators: install games, Setup
 *
 * Games run in a sandboxed iframe (no access to the Kolibri session). They
 * send requests with postMessage through sdk.js; handleGameMessage() below
 * checks each one and calls the server on the game's behalf.
 */
(function () {
  "use strict";

  // Relative URLs (api/..., play/...) need the page URL to end with "/".
  if (!location.pathname.endsWith("/")) {
    location.replace(location.pathname + "/" + location.search + location.hash);
    return;
  }

  var API_VERSION = 2; // must match sdk.js
  var CSRF = document.querySelector('meta[name="csrf-token"]').content;
  var KOLIBRI_ROOT = document.querySelector('meta[name="kolibri-root"]').content || "/";
  var view = document.getElementById("view");
  var barMid = document.getElementById("bar-mid");
  var barEnd = document.getElementById("bar-end");

  var S = { me: null, platform: null, games: null, classes: null, play: null };

  // ================================================================ helpers

  // el("p", {class: "x", text: "hi", onclick: fn}, [children]) makes an element.
  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      var v = attrs[k];
      if (v === null || v === undefined || v === false) return;
      if (k === "text") node.textContent = v;
      else if (k === "class") node.className = v;
      else if (k.slice(0, 2) === "on") node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v === true ? "" : v);
    });
    (children || []).forEach(function (c) {
      if (c === null || c === undefined || c === false) return;
      node.appendChild(typeof c === "string" || typeof c === "number" ? document.createTextNode(String(c)) : c);
    });
    return node;
  }

  // Calls the server. opts.body sends JSON; opts.raw sends a file as it is.
  function api(path, opts) {
    opts = opts || {};
    var init = { method: opts.method || "GET", credentials: "same-origin", headers: { Accept: "application/json" } };
    if (opts.body !== undefined || opts.raw !== undefined) {
      init.method = opts.method || "POST";
      init.headers["X-CSRFToken"] = CSRF;
      if (opts.raw !== undefined) {
        init.headers["Content-Type"] = "application/zip";
        init.body = opts.raw;
      } else {
        init.headers["Content-Type"] = "application/json";
        init.body = JSON.stringify(opts.body);
      }
    }
    return fetch(path, init).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (data) {
        if (!res.ok) {
          var err = new Error(data.message || (res.status === 413
            ? "That file is too big for this server."
            : "The server didn't answer (" + res.status + "). Check that Kolibri is running."));
          err.code = data.error || "http_" + res.status;
          err.status = res.status;
          err.fields = data.fields;
          throw err;
        }
        return data;
      });
    }, function () {
      var err = new Error("Can't reach Kolibri. Check your connection to the server.");
      err.code = "offline";
      throw err;
    });
  }

  function gamePath(key, rest) { return "api/games/" + encodeURIComponent(key) + (rest || ""); }
  function q(params) {
    var parts = Object.keys(params).filter(function (k) { return params[k] !== null && params[k] !== undefined && params[k] !== ""; })
      .map(function (k) { return k + "=" + encodeURIComponent(params[k]); });
    return parts.length ? "?" + parts.join("&") : "";
  }

  function clock(seconds) {
    if (seconds === null || seconds === undefined) return "";
    seconds = Math.max(0, Math.round(seconds));
    var h = Math.floor(seconds / 3600), m = Math.floor((seconds % 3600) / 60), s = seconds % 60;
    var mm = (h ? (m < 10 ? "0" : "") : "") + m;
    return (h ? h + ":" : "") + mm + ":" + (s < 10 ? "0" : "") + s;
  }

  function scoreText(scoring, score) {
    if (score === null || score === undefined) return "";
    var n = Number(score).toFixed(scoring && scoring.decimals ? scoring.decimals : 0);
    var unit = scoring && scoring.unit;
    if (unit && Number(score) === 1) unit = unit.replace(/s$/, "");
    return unit ? n + " " + unit : n;
  }

  function when(iso) {
    if (!iso) return "";
    var d = new Date(iso);
    return d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" }) + " " +
      d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  }

  // <input type="datetime-local"> works in local time without a time zone.
  function toLocalInput(iso) {
    if (!iso) return "";
    var d = new Date(iso), pad = function (n) { return (n < 10 ? "0" : "") + n; };
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) + "T" + pad(d.getHours()) + ":" + pad(d.getMinutes());
  }
  function fromLocalInput(value) { return value ? new Date(value).toISOString() : null; }

  function plural(n, word) {
    word = String(word || "").toLowerCase();
    return n + " " + (n === 1 ? word : word.replace(/y$/, "ie") + "s");
  }

  function rankWord(rank) {
    var n = rank % 100, s = n > 10 && n < 14 ? "th" : ({ 1: "st", 2: "nd", 3: "rd" }[rank % 10] || "th");
    return rank + s;
  }

  function toast(text) {
    var t = document.getElementById("toast");
    t.textContent = text;
    t.hidden = false;
    clearTimeout(toast.timer);
    toast.timer = setTimeout(function () { t.hidden = true; }, 3500);
  }

  function setView(nodes, opts) {
    opts = opts || {};
    document.body.classList.toggle("playing", !!opts.playing);
    view.innerHTML = "";
    nodes.forEach(function (n) { if (n) view.appendChild(n); });
    barMid.innerHTML = "";
    (opts.mid || []).forEach(function (n) { barMid.appendChild(n); });
    renderBarEnd(opts.playing);
    if (!opts.keepScroll) window.scrollTo(0, 0);
    document.title = (opts.title ? opts.title + " - " : "") + "Games";
  }

  function renderBarEnd(playing) {
    barEnd.innerHTML = "";
    if (!S.me) return;
    if (S.me.role === "admin" && !playing) barEnd.appendChild(el("a", { href: "#/status", text: "Setup" }));
    barEnd.appendChild(el("span", { class: "who", text: S.me.name }));
  }

  function pageHead(crumbs, title, intro, actions) {
    return el("div", { class: "page-head" }, [
      el("div", {}, [
        el("nav", { class: "crumbs", "aria-label": "Where you are" }, crumbs.map(function (c) {
          return el("a", { class: "crumb", href: c[1], text: c[0] });
        })),
        el("h1", { text: title }),
        intro ? el("p", { text: intro }) : null
      ]),
      actions && actions.length ? el("div", { class: "row" }, actions) : null
    ]);
  }

  function showError(err) {
    if (err.code === "signin") {
      setView([el("div", { class: "empty" }, [
        el("h2", { text: "Sign in to play" }),
        el("p", { text: "Games use your Kolibri account to save your results." }),
        // Kolibri's sign-in page sends people back to "next" once they've signed in.
        // Kolibri adds "next" to its sign-in address without re-encoding it, so the
        // "#" of the game address is encoded twice to survive that step.
        el("p", {}, [el("a", {
          class: "button primary",
          href: KOLIBRI_ROOT + "?next=" + encodeURIComponent(location.pathname + location.hash.replace("#", "%23")),
          text: "Sign in"
        })])
      ])]);
      return;
    }
    setView([el("div", { class: "empty" }, [
      el("h2", { text: "Something went wrong" }),
      el("p", { text: err.message }),
      el("p", {}, [el("a", { class: "button", href: "#/", text: "Back to games" })])
    ])]);
  }

  function loadGames(force) {
    if (S.games && !force) return Promise.resolve(S.games);
    return api("api/games").then(function (data) {
      S.me = data.me;
      S.platform = data.platform;
      S.games = data.games;
      return data.games;
    });
  }

  function findGame(key) {
    return loadGames().then(function (games) {
      var g = games.filter(function (x) { return x.key === key; })[0];
      if (!g) {
        var err = new Error("That game isn't on this device any more.");
        err.code = "not_found";
        throw err;
      }
      return g;
    });
  }

  function loadClasses() {
    if (S.classes) return Promise.resolve(S.classes);
    return api("api/classes").then(function (data) { S.classes = data; return data; });
  }

  function isCoach() { return S.me && S.me.role !== "learner"; }
  function isRace(g) { return g.service === "wikipedia-race"; }

  // ================================================================ lobby

  function renderLobby() {
    stopPlay();
    loadGames(true).then(function (games) {
      var head = el("div", { class: "page-head" }, [
        el("div", {}, [
          el("h1", { text: "Games" }),
          el("p", { text: games.length ? "Your results are saved to your Kolibri account." : "" })
        ]),
        isCoach() && games.some(isRace) ? el("div", { class: "row" }, [el("a", { class: "button quiet", href: "#/lists", text: "Article lists" })]) : null
      ]);
      if (!games.length) {
        setView([head, emptyShelf()]);
        return;
      }
      var classroom = games.filter(function (g) { return g.type === "classroom" && g.playable; });
      var freePlay = games.filter(function (g) { return classroom.indexOf(g) < 0; });
      setView([
        head,
        shelfSection("free-play", "Free-play Games", "Play these here, anytime.", freePlay),
        shelfSection("classroom", "Classroom Games", "Play these in Learn. Here you can see their scoreboards.", classroom)
      ]);
    }).catch(showError);
  }

  function shelfSection(id, title, intro, games) {
    if (!games.length) return null;
    var list = el("ul", { class: "shelf" });
    games.forEach(function (g) { list.appendChild(gameCard(g)); });
    return el("section", { class: "shelf-section", id: id, "aria-labelledby": id + "-title" }, [
      el("h2", { class: "shelf-title", id: id + "-title", text: title }),
      el("p", { class: "shelf-intro", text: intro }),
      list
    ]);
  }

  function emptyShelf() {
    var admin = S.me && S.me.role === "admin";
    return el("div", { class: "empty" }, [
      el("h2", { text: "No games on this device yet" }),
      admin
        ? el("p", {}, ["Install Free-play Games on the ", el("a", { href: "#/status", text: "Setup page" }),
            ". Classroom Games come in Kolibri channels."])
        : el("p", { text: "Ask your coach or administrator to add some." })
    ]);
  }

  function rulesNote(counts, firstUsed) {
    if (counts === "first") {
      if (firstUsed) return el("span", { class: "rule-note practice", text: "Your first attempt is done. Playing again is practice." });
      return el("span", { class: "rule-note", text: "Your first attempt counts on the scoreboard." });
    }
    return el("span", { class: "rule-note", text: "Your best attempt counts on the scoreboard." });
  }

  // Learn's page for one resource. The games page is at <prefix>/<lang>/kolibri_games/,
  // and Learn is at <prefix>/<lang>/learn/.
  function learnUrl(nodeId) {
    return "../learn/#/topics/c/" + encodeURIComponent(nodeId);
  }

  function classroomCard(g) {
    var s = g.summary || {};
    var label = (g.scoreboards && g.scoreboards.board_label) || "Scoreboard";
    var facts = [
      el("span", { text: plural((g.resources || []).length, "resource") + " in Learn" }),
      el("span", { text: s.boards ? "You have scores on " + plural(s.boards, label) : "No scores from you yet" })
    ];
    var actions = [el("a", { class: "button primary", href: "#/scores/" + g.key, text: "Scoreboard" })];
    if ((g.resources || []).length === 1) {
      actions.push(el("a", { class: "button quiet", href: learnUrl(g.resources[0].node_id), text: "Open in Learn" }));
    }
    if (isCoach()) actions.push(el("a", { class: "button quiet", href: "#/settings/" + g.key, text: "Settings" }));
    return el("li", { class: "game" }, [
      el("img", { class: "game-icon", src: gamePath(g.key, "/icon"), alt: "" }),
      el("div", {}, [
        el("h3", { text: g.title }),
        g.description ? el("p", { class: "desc", text: g.description }) : null,
        el("div", { class: "facts" }, facts)
      ]),
      el("div", { class: "row" }, actions)
    ]);
  }

  function challengeLine(g, c) {
    var bits = [];
    if (c.state === "open") bits.push(c.closes_at ? "Closes " + when(c.closes_at) : "Open");
    else if (c.state === "upcoming") bits.push("Opens " + when(c.opens_at));
    else bits.push("Closed " + when(c.closes_at));
    if (isCoach()) bits.push(c.class_name);
    var mine = c.mine;
    if (mine && mine.counted && g.scoring) bits.push("Your result: " + scoreText(g.scoring, mine.counted.score));
    else if (mine && mine.attempts && c.state !== "upcoming") bits.push("Not finished yet");
    var actions = [];
    var base = g.key + "/c/" + c.id;
    if (c.state === "open" && c.mine !== undefined) {
      actions.push(el("a", { class: "button primary small", href: "#/play/" + base, text: mine && mine.first_used && c.counts === "first" ? "Practice" : "Play" }));
    }
    if (g.scoring && c.state !== "upcoming") actions.push(el("a", { class: "button quiet small", href: "#/board/" + base, text: "Scoreboard" }));
    return el("li", { class: "challenge " + c.state }, [
      el("div", {}, [
        el("span", { class: "tag " + c.state, text: { open: "Challenge", upcoming: "Coming up", closed: "Closed" }[c.state] }),
        el("b", { text: c.title }),
        c.start ? el("span", { class: "pair-text", text: c.start + " → " + c.goal }) : null,
        el("div", { class: "facts", text: bits.join(" · ") })
      ]),
      el("div", { class: "row" }, actions)
    ]);
  }

  function gameCard(g) {
    if (g.type === "classroom" && g.playable) return classroomCard(g);
    var unplayable = !g.playable;
    var facts = [];
    var s = g.summary;
    var freeBoard = g.scoring && g.free_play_scoreboard;
    if (s && freeBoard) {
      if (s.counted) {
        facts.push(el("span", {}, ["Your free-play result ", el("b", { text: scoreText(g.scoring, s.counted.score) }), " in " + clock(s.counted.seconds)]));
      } else {
        facts.push(el("span", { text: s.attempts ? "No finished result yet" : "Not played yet" }));
      }
    } else if (s) {
      facts.push(el("span", { text: s.attempts ? "Played " + plural(s.attempts, "time") : "Not played yet" }));
    }
    var actions = [];
    if (!unplayable) {
      actions.push(el("a", { class: "button primary", href: "#/play/" + g.key, text: "Free play" }));
      if (freeBoard) actions.push(el("a", { class: "button quiet", href: "#/board/" + g.key, text: "Scoreboard" }));
    }
    if (isCoach() && g.id && !unplayable) {
      actions.push(el("a", { class: "button quiet", href: "#/challenges/" + g.key, text: "Challenges" }));
      if (g.scoring) actions.push(el("a", { class: "button quiet", href: "#/results/" + g.key, text: "Results" }));
      actions.push(el("a", { class: "button quiet", href: "#/settings/" + g.key, text: "Settings" }));
    }
    var challenges = (g.challenges || []);
    return el("li", { class: "game" + (unplayable ? " unplayable" : "") }, [
      g.id ? el("img", { class: "game-icon", src: gamePath(g.key, "/icon"), alt: "" }) : el("div", { class: "game-icon" }),
      el("div", {}, [
        el("h3", { text: g.title }),
        g.description ? el("p", { class: "desc", text: g.description }) : null,
        facts.length ? el("div", { class: "facts" }, facts) : null,
        !unplayable && freeBoard ? el("div", { class: "facts", style: "margin-top:.35rem" }, [rulesNote(s ? s.counts : g.scoring.counts, s && s.first_used)]) : null,
        unplayable ? el("ul", { class: "problems" }, g.problems.map(function (p) { return el("li", { text: p }); })) : null
      ]),
      challenges.length ? el("ul", { class: "challenges" }, challenges.map(function (c) { return challengeLine(g, c); })) : null,
      actions.length ? el("div", { class: "row" }, actions) : null
    ]);
  }

  // ================================================================ play

  function stopPlay() {
    if (!S.play) return;
    clearInterval(S.play.timer);
    window.removeEventListener("message", S.play.listener);
    S.play = null;
  }

  function renderPlay(key, challengeId) {
    stopPlay();
    var frameWrap = el("div", { class: "loading", text: "Opening the game…" });
    setView([frameWrap], { playing: true });
    Promise.all([loadGames(), api(gamePath(key, q({ challenge: challengeId })))]).then(function (res) {
      var session = res[1];
      var play = {
        key: key,
        challengeId: challengeId,
        session: session,
        attempt: null,
        deadline: null,
        timeUp: false,
        frame: el("iframe", {
          class: "game-frame",
          title: session.game.title,
          src: session.play_url,
          // No allow-same-origin: the game gets an opaque origin and can't use the Kolibri session.
          sandbox: "allow-scripts allow-forms allow-pointer-lock",
          allow: "fullscreen; autoplay",
          referrerpolicy: "no-referrer"
        })
      };
      play.listener = function (e) { handleGameMessage(play, e); };
      window.addEventListener("message", play.listener);
      S.play = play;

      play.timeChip = el("span", { class: "chip", hidden: true });
      play.ruleChip = el("span", { class: "chip" });
      var title = session.game.title + (session.challenge ? ": " + session.challenge.title : "");
      setView([play.frame], {
        playing: true,
        title: session.game.title,
        mid: [
          el("button", { class: "quiet", type: "button", text: "Back to games", onclick: function () { location.hash = "#/"; } }),
          el("span", { class: "play-title", text: title }),
          play.ruleChip,
          play.timeChip
        ]
      });
      updateRuleChip(play, null);
      play.frame.focus();
    }).catch(showError);
  }

  function updateRuleChip(play, attempt) {
    var s = play.session;
    var chip = play.ruleChip;
    var ranked = s.game.scoring && (s.challenge || s.rules.free_play_scoreboard);
    if (!ranked) { chip.hidden = true; return; }
    chip.hidden = false;
    if (s.rules.counts === "first") {
      var practice = attempt ? attempt.practice : (s.summary && s.summary.first_used);
      chip.textContent = practice ? "Practice" : "This attempt counts";
    } else {
      chip.textContent = "Best attempt counts";
    }
  }

  function startClock(play, limit, elapsed) {
    clearInterval(play.timer);
    play.timeChip.hidden = !limit;
    if (!limit) return;
    play.deadline = Date.now() + (limit - (elapsed || 0)) * 1000;
    play.timeUp = false;
    var tick = function () {
      var left = (play.deadline - Date.now()) / 1000;
      play.timeChip.textContent = left > 0 ? clock(left) + " left" : "Time's up";
      play.timeChip.className = "chip" + (left <= 0 ? " out" : left < 60 ? " low" : "");
      if (left <= 0 && !play.timeUp) {
        play.timeUp = true;
        clearInterval(play.timer);
        sendToGame(play, { kg: API_VERSION, event: "timeup" });
      }
    };
    tick();
    play.timer = setInterval(tick, 500);
  }

  function sendToGame(play, msg) {
    if (play.frame.contentWindow) play.frame.contentWindow.postMessage(msg, "*");
  }

  function needAttempt(play) {
    if (!play.attempt) {
      var err = new Error("Start the game first.");
      err.code = "no_attempt";
      throw err;
    }
    return play.attempt.id;
  }

  // What a game can ask for (see sdk.js). Each one returns a value or a Promise.
  var METHODS = {
    hello: function (play) {
      var s = play.session;
      return {
        game: s.game,
        player: s.player,
        platform: s.platform,
        settings: s.settings,
        rules: s.rules,
        challenge: s.challenge,
        summary: s.summary,
        preview: false
      };
    },
    "attempt.start": function (play, params) {
      return api(gamePath(play.key, "/attempts"), { body: { resume: params.resume !== false, challenge: play.challengeId } }).then(function (data) {
        play.attempt = data.attempt;
        updateRuleChip(play, data.attempt);
        startClock(play, data.time_limit, data.elapsed);
        return data;
      });
    },
    "attempt.move": function (play, params) {
      return api(gamePath(play.key, "/attempts/" + needAttempt(play) + "/moves"), { body: { type: params.type, data: params.data } });
    },
    "attempt.finish": function (play, params) {
      return api(gamePath(play.key, "/attempts/" + needAttempt(play) + "/finish"), { body: params }).then(function (data) {
        clearInterval(play.timer);
        play.timeChip.hidden = true;
        play.attempt = null;
        play.session.summary.first_used = true;
        S.games = null; // card summaries changed
        toast(data.attempt.practice ? "Practice result saved." : "Result saved.");
        return data;
      });
    },
    "attempt.abandon": function (play) {
      if (!play.attempt) return { ok: true };
      var id = play.attempt.id;
      play.attempt = null;
      clearInterval(play.timer);
      play.timeChip.hidden = true;
      return api(gamePath(play.key, "/attempts/" + id + "/abandon"), { body: {} });
    },
    "scoreboard.get": function (play) { return api(gamePath(play.key, "/scoreboard" + q({ challenge: play.challengeId }))); },
    "results.mine": function (play) { return api(gamePath(play.key, "/mine" + q({ challenge: play.challengeId }))); },
    "state.get": function (play) { return api(gamePath(play.key, "/state")).then(function (d) { return d.data; }); },
    "state.set": function (play, params) { return api(gamePath(play.key, "/state"), { body: { data: params.data } }); },
    exit: function () { setTimeout(function () { location.hash = "#/"; }, 0); return { ok: true }; }
  };

  function handleGameMessage(play, e) {
    // Only accept messages from this game's own frame.
    if (!play.frame || e.source !== play.frame.contentWindow) return;
    var msg = e.data;
    if (!msg || typeof msg.method !== "string" || typeof msg.id !== "number") return;
    var reply = function (payload) { sendToGame(play, Object.assign({ kg: msg.kg, id: msg.id }, payload)); };
    if (msg.kg !== API_VERSION) {
      reply({ error: { code: "old_game", message: "This game was made for another version of Kolibri Games. Ask your administrator to update it." } });
      return;
    }
    var fn = METHODS[msg.method];
    if (!fn) {
      reply({ error: { code: "unknown_method", message: "Kolibri Games doesn't know '" + msg.method + "'." } });
      return;
    }
    Promise.resolve().then(function () { return fn(play, msg.params || {}); }).then(
      function (result) { reply({ result: result === undefined ? null : result }); },
      function (err) {
        if (err.code === "time_up" || err.code === "closed") {
          play.attempt = null;
          sendToGame(play, { kg: API_VERSION, event: "timeup" });
        }
        reply({ error: { code: err.code || "error", message: err.message } });
      }
    );
  }

  // ================================================================ scoreboard

  function classPicker(selected, onChange, allowEveryone) {
    return loadClasses().then(function (data) {
      if (!data.classes.length && !data.whole_facility) return null;
      var select = el("select", { "aria-label": "Class", onchange: function () { onChange(select.value); } });
      if (allowEveryone) select.appendChild(el("option", { value: "", text: data.whole_facility ? "Everyone" : "Everyone who played" }));
      data.classes.forEach(function (c) { select.appendChild(el("option", { value: c.id, text: c.name })); });
      if (selected) select.value = selected;
      return select;
    });
  }

  function renderBoard(key, challengeId, classId) {
    stopPlay();
    findGame(key).then(function (g) {
      return Promise.all([
        api(gamePath(key, "/scoreboard" + q({ challenge: challengeId, "class": classId }))),
        isCoach() && !challengeId ? classPicker(classId, function (v) { renderBoard(key, challengeId, v); }, true) : null
      ]).then(function (res) {
        var data = res[0], picker = res[1], c = data.challenge;
        var title = c ? c.title : g.title + " scoreboard";
        var intro = [];
        if (c) intro.push(g.title + " challenge for " + c.class_name + ".");
        else intro.push("Free play.");
        intro.push(data.counts === "first" ? "Each player's first attempt." : "Each player's best attempt.");
        var playHref = "#/play/" + key + (c ? "/c/" + c.id : "");
        var canPlay = !c || c.state === "open";
        var head = pageHead([["Games", "#/"]], title, intro.join(" "), [
          picker, canPlay ? el("a", { class: "button primary", href: playHref, text: "Play" }) : null
        ]);
        var parts = [head];
        if (c) parts.push(challengeFacts(g, c));
        if (data.no_scoreboard) {
          parts.push(el("div", { class: "empty" }, [el("h2", { text: "No free-play scoreboard" }),
            el("p", { text: "Every free-play round of " + g.title + " is different, so results are only ranked in challenges." })]));
        } else if (!data.rows.length) {
          parts.push(el("div", { class: "empty" }, [el("h2", { text: "No results yet" }), el("p", { text: "Be the first to finish." })]));
        } else {
          parts.push(el("div", { class: "panel" }, [boardTable(g, data.rows)]));
        }
        if (data.visibility === "hidden" && !isCoach()) parts.push(el("p", { class: "footnote", text: "Your coach has hidden other players' results." }));
        if (data.visibility === "initials" && !isCoach()) parts.push(el("p", { class: "footnote", text: "Other players are shown by their initials." }));
        if (c && c.state !== "closed" && isRace(g)) parts.push(el("p", { class: "footnote", text: "Everyone's routes are shown here when the challenge closes." }));
        setView(parts, { title: g.title });
      });
    }).catch(showError);
  }

  // Dates, start and goal, and (for Wiki BLAZE) the shortest route.
  function challengeFacts(g, c) {
    var items = [
      el("dt", { text: "Open" }),
      el("dd", { text: when(c.opens_at) + (c.closes_at ? " to " + when(c.closes_at) : ", no closing date") + " (" + ({ open: "open now", upcoming: "not open yet", closed: "closed" }[c.state]) + ")" })
    ];
    if (c.start) items.push(el("dt", { text: "Start and goal" }), el("dd", { text: c.start + " → " + c.goal }));
    if (c.time_limit) items.push(el("dt", { text: "Time limit" }), el("dd", { text: plural(c.time_limit, "minute") }));
    if (c.best) items.push(el("dt", { text: "Shortest route" }), el("dd", { text: bestText(c.best) }));
    return el("div", { class: "panel facts-panel" }, [el("dl", { class: "kv" }, items)]);
  }

  function bestText(best) {
    if (best.status === "found") return plural(best.steps, "link") + ": " + best.route.join(" → ");
    if (best.status === "working") return "Still working it out… (refresh in a minute)";
    if (best.status === "not_found") return "These articles aren't connected with this article list.";
    if (best.status === "too_far") return "Too far apart to work out on this device (more than a few links).";
    return "Couldn't work it out." + (best.message ? " " + best.message : "");
  }

  function boardTable(g, rows) {
    var label = (g.scoring && g.scoring.label) || "Score";
    var showRoutes = rows.some(function (r) { return r.route; });
    var tbody = el("tbody");
    rows.forEach(function (r) {
      tbody.appendChild(el("tr", { class: r.me ? "me" : "" }, [
        el("td", {}, [el("span", { class: "rank r" + r.rank, text: String(r.rank) })]),
        el("td", { text: r.name + (r.me ? " (you)" : "") }),
        el("td", { class: "num", text: scoreText(g.scoring, r.score) }),
        el("td", { class: "num", text: clock(r.seconds) }),
        showRoutes ? el("td", { class: "route-cell", text: (r.route || []).join(" → ") }) : null
      ]));
    });
    return el("table", {}, [
      el("thead", {}, [el("tr", {}, [el("th", { text: "Rank" }), el("th", { text: "Name" }),
        el("th", { class: "num", text: label }), el("th", { class: "num", text: "Time" }),
        showRoutes ? el("th", { text: "Route" }) : null])]),
      tbody
    ]);
  }

  // ================================================================ Classroom Games

  function fieldText(f, v) {
    if (v === null || v === undefined) return "";
    if (f.seconds) return clock(v);
    var n = Number(v).toFixed(f.decimals || 0);
    if (!f.unit) return n;
    return f.unit === "%" ? n + "%" : n + " " + f.unit;
  }

  function renderScores(key, boardId, classId) {
    stopPlay();
    findGame(key).then(function (g) {
      return Promise.all([
        api(gamePath(key, "/boards" + q({ "class": classId }))),
        isCoach() ? classPicker(classId, function (v) { renderScores(key, boardId, v); }, true) : null
      ]).then(function (res) { drawScores(g, res[0], res[1], boardId, classId); });
    }).catch(showError);
  }

  function drawScores(g, data, picker, boardId, classId) {
    var spec = data.spec;
    var csv = gamePath(g.key, "/boards" + q({ format: "csv", "class": classId }));
    var head = pageHead([["Games", "#/"]], g.title + " scoreboard",
      "Scores from playing " + g.title + " in Learn. Each learner's best result counts.",
      [picker, isCoach() && data.boards.length ? el("a", { class: "button", href: csv, text: "Download CSV" }) : null]);
    var notes = [];
    if (data.visibility === "hidden" && !isCoach()) notes.push("Your coach has hidden other players' results.");
    if (data.visibility === "initials" && !isCoach()) notes.push("Other players are shown by their initials.");
    var footer = notes.map(function (n) { return el("p", { class: "footnote", text: n }); });

    if (!data.boards.length) {
      setView([head, el("div", { class: "empty" }, [
        el("h2", { text: "No scores yet" }),
        el("p", { text: classId ? "No one in this class has a score yet." : "Scores appear here after learners play " + g.title + " in Learn." }),
        resourceLinks(data.resources)
      ])].concat(footer), { title: g.title });
      return;
    }
    var board = data.boards.filter(function (b) { return b.id === boardId; })[0] || data.boards[0];
    var nav = el("nav", { class: "boards", "aria-label": spec.board_label });
    data.boards.forEach(function (b) {
      var mine = b.mine ? "You: " + rankWord(b.mine.rank) + " of " + b.players : plural(b.players, "player");
      nav.appendChild(el("a", {
        class: "board-link" + (b === board ? " current" : ""),
        href: "#/scores/" + g.key + "/" + encodeURIComponent(b.id) + (classId ? "/" + classId : ""),
        "aria-current": b === board ? "page" : null
      }, [el("span", { class: "board-name", text: b.name }), el("span", { class: "board-sub", text: mine })]));
    });
    setView([head, el("div", { class: "scores" }, [nav, boardPanel(spec, board)])].concat(footer), { title: g.title, keepScroll: !!boardId });
  }

  function resourceLinks(resources) {
    if (!resources || !resources.length) return null;
    return el("p", {}, ["Open in Learn: "].concat(resources.map(function (r, i) {
      return [i ? ", " : "", el("a", { href: learnUrl(r.node_id), text: r.title })];
    }).reduce(function (a, b) { return a.concat(b); }, [])));
  }

  function boardPanel(spec, board) {
    var fields = spec.fields;
    var tbody = el("tbody");
    board.rows.forEach(function (r) {
      tbody.appendChild(el("tr", { class: r.me ? "me" : "" }, [
        el("td", {}, [el("span", { class: "rank r" + r.rank, text: String(r.rank) })]),
        el("td", { text: r.name + (r.me ? " (you)" : "") })
      ].concat(fields.map(function (f) { return el("td", { class: "num", text: fieldText(f, r.values[f.key]) }); }))));
    });
    var table = el("table", {}, [
      el("thead", {}, [el("tr", {}, [el("th", { text: "Rank" }), el("th", { text: "Name" })].concat(
        fields.map(function (f) { return el("th", { class: "num", text: f.label }); })))]),
      tbody
    ]);
    var ranked = spec.rank_by.map(function (k) {
      var f = fields.filter(function (x) { return x.key === k; })[0];
      return f.label.toLowerCase() + (f.order === "asc" ? " (lower is better)" : " (higher is better)");
    });
    return el("section", { class: "panel board" }, [
      el("h2", { text: board.name }),
      el("p", { class: "footnote", text: "Ranked by " + ranked.join(", then ") + "." }),
      board.rows.length ? table : el("p", { text: "You don't have a score here yet." }),
      resourceLinks(board.resources)
    ]);
  }

  // ================================================================ results (coaches)

  function renderResults(key, challengeId, classId) {
    stopPlay();
    findGame(key).then(function (g) {
      return loadClasses().then(function (classes) {
        if (!challengeId && !classes.whole_facility && !classId && classes.classes.length) classId = classes.classes[0].id;
        return Promise.all([
          api(gamePath(key, "/results" + q({ challenge: challengeId, "class": classId }))),
          challengeId ? null : classPicker(classId, function (v) { renderResults(key, null, v); }, classes.whole_facility)
        ]).then(function (res) { drawResults(g, res[0], res[1], challengeId, classId); });
      });
    }).catch(showError);
  }

  function drawResults(g, data, picker, challengeId, classId) {
    var key = g.key, c = data.challenge;
    var csv = gamePath(key, "/results" + q({ format: "csv", challenge: challengeId, "class": classId }));
    var crumbs = [["Games", "#/"]];
    if (c) crumbs.push(["Challenges", "#/challenges/" + key]);
    var head = pageHead(crumbs, (c ? c.title : g.title + " free play") + " results",
      data.counts === "first"
        ? "The counted result is each learner's first attempt. Later attempts are practice."
        : "The counted result is each learner's best attempt.",
      [picker, el("a", { class: "button", href: csv, text: "Download CSV" })]);
    if (!data.rows.length) {
      setView([head, el("div", { class: "empty" }, [el("h2", { text: "Nobody has played yet" }),
        el("p", { text: classId || c ? "No one in this class has played yet." : "Results appear here once learners play." })])], { title: g.title });
      return;
    }
    var label = (data.scoring && data.scoring.label) || "Score";
    var tbody = el("tbody");
    data.rows.forEach(function (r) {
      var counted = r.counted, best = r.best;
      var historyRow = el("tr", { class: "history", hidden: true }, [el("td", { colspan: "7" }, [historyList(g, r)])]);
      var toggle = el("button", { class: "quiet", type: "button", text: "History", "aria-expanded": "false",
        onclick: function () {
          historyRow.hidden = !historyRow.hidden;
          toggle.setAttribute("aria-expanded", String(!historyRow.hidden));
        } });
      var reset = el("button", { class: "quiet danger", type: "button", text: "Reset", title: "Give this learner a fresh first attempt",
        onclick: function () {
          if (!confirm("Reset " + r.name + "'s results? Their attempts are kept for your records, but their next attempt will count as their first.")) return;
          api(gamePath(key, "/results/" + r.user_id + "/reset"), { body: { challenge: challengeId } })
            .then(function () { toast("Reset " + r.name + "."); renderResults(key, challengeId, classId); })
            .catch(function (e) { toast(e.message); });
        } });
      tbody.appendChild(el("tr", {}, [
        el("td", {}, [r.rank ? el("span", { class: "rank r" + r.rank, text: String(r.rank) }) : ""]),
        el("td", { text: r.name }),
        el("td", { class: "num" }, counted ? [scoreText(g.scoring, counted.score)] : [r.attempts ? "Didn't finish" : "Not played"]),
        el("td", { class: "num", text: counted ? clock(counted.seconds) : "" }),
        el("td", { class: "num", text: best ? scoreText(g.scoring, best.score) : "" }),
        el("td", { class: "num", text: String(r.attempts) }),
        el("td", {}, [el("div", { class: "row" }, [r.attempts ? toggle : null, r.attempts || r.reset_attempts ? reset : null])])
      ]));
      tbody.appendChild(historyRow);
    });
    var table = el("table", {}, [
      el("thead", {}, [el("tr", {}, [
        el("th", { text: "Rank" }), el("th", { text: "Learner" }), el("th", { class: "num", text: "Counted " + label.toLowerCase() }),
        el("th", { class: "num", text: "Time" }), el("th", { class: "num", text: "Best" }), el("th", { class: "num", text: "Attempts" }),
        el("th", { text: "" })
      ])]),
      tbody
    ]);
    setView([head, c ? challengeFacts(g, c) : null, el("div", { class: "panel" }, [table])], { title: g.title });
  }

  // One learner's attempts. Wiki BLAZE attempts show the route and every move.
  function historyList(g, r) {
    var list = el("ol");
    r.history.forEach(function (a) {
      var bits = ["Attempt " + a.number + ": "];
      if (a.status === "finished") bits.push(scoreText(g.scoring, a.score) + " in " + clock(a.seconds));
      else bits.push({ started: "in progress", abandoned: "left without finishing", expired: "ran out of time" }[a.status] || a.status);
      var route = a.detail && a.detail.route;
      var moves = (a.events || []);
      var details = null;
      if (isRace(g) && moves.length) {
        details = el("details", {}, [
          el("summary", { text: "Every step (" + moves.length + ")" }),
          el("ol", { class: "moves" }, moves.map(function (m) {
            var d = m.data || {};
            var text = m.type === "back" ? "Went back to " + d.title : "Followed a link to " + d.title;
            return el("li", { text: clock(m.t) + "  " + text + " (" + plural(d.steps || 0, "link") + " so far)" });
          }))
        ]);
      } else if (moves.length || (a.detail && Object.keys(a.detail).length)) {
        details = el("details", {}, [
          el("summary", { text: "Moves and details" }),
          el("pre", { class: "detail", text: JSON.stringify({ detail: a.detail, moves: moves }, null, 1) })
        ]);
      }
      list.appendChild(el("li", {}, [
        bits.join(""),
        a.practice ? el("span", { class: "tag", text: "practice" }) : null,
        el("span", { class: "footnote", text: "  " + when(a.started_at) }),
        route ? el("div", { class: "route-line", text: route.join(" → ") }) : null,
        details
      ]));
    });
    if (r.reset_attempts) list.appendChild(el("li", { class: "footnote", text: r.reset_attempts + " earlier attempt(s) were reset." }));
    return list;
  }

  // ================================================================ forms

  // One form field for a game setting. Returns {node, input, field, err, read()}.
  // "article" fields suggest Wikipedia titles as the coach types; "article_list"
  // fields choose a list (the choices come from the server).
  function fieldInput(field, value, group, ctx) {
    var id = "f-" + group + "-" + field.key;
    var input, help = field.help ? el("div", { class: "help", text: field.help }) : null;
    var err = el("div", { class: "err", hidden: true });
    if (field.type === "boolean") {
      input = el("input", { id: id, type: "checkbox", checked: !!value });
      return { node: el("div", { class: "field check" }, [input, el("label", { for: id, text: field.label }), err]), input: input, field: field, err: err,
        read: function () { return input.checked; } };
    }
    if (field.type === "choice" || field.type === "article_list") {
      input = el("select", { id: id });
      (field.choices || []).forEach(function (c, i) {
        input.appendChild(el("option", { value: String(i), text: c.label }));
        if (c.value === value) input.value = String(i);
      });
      var extra = field.type === "article_list" ? el("div", { class: "help" }, [el("a", { href: "#/lists", text: "Make or change article lists" })]) : null;
      return { node: el("div", { class: "field" }, [el("label", { for: id, text: field.label }), help, input, extra, err]), input: input, field: field, err: err,
        read: function () { return field.choices[Number(input.value)].value; } };
    }
    if (field.type === "article") {
      var listId = id + "-options";
      input = el("input", { id: id, type: "text", value: value || "", list: listId, autocomplete: "off", placeholder: "Type to search" });
      var options = el("datalist", { id: listId });
      var timer = null;
      input.addEventListener("input", function () {
        clearTimeout(timer);
        var text = input.value.trim();
        if (text.length < 2 || !ctx || !ctx.gameKey) return;
        timer = setTimeout(function () {
          var list = ctx.listValue ? ctx.listValue() : "default";
          api(gamePath(ctx.gameKey, "/articles" + q({ q: text, list: list }))).then(function (data) {
            options.innerHTML = "";
            data.articles.forEach(function (a) { options.appendChild(el("option", { value: a.title })); });
          }).catch(function () { /* suggestions are only a help */ });
        }, 250);
      });
      return { node: el("div", { class: "field" }, [el("label", { for: id, text: field.label }), help, input, options, err]), input: input, field: field, err: err,
        read: function () { return input.value.trim(); } };
    }
    input = el("input", {
      id: id,
      type: field.type === "text" ? "text" : "number",
      value: value === null || value === undefined ? "" : String(value),
      min: field.min, max: field.max,
      step: field.type === "integer" ? "1" : field.type === "number" ? "any" : null
    });
    return { node: el("div", { class: "field" }, [el("label", { for: id, text: field.label }), help, input, err]), input: input, field: field, err: err,
      read: function () {
        if (field.type === "text") return input.value;
        return input.value === "" ? null : Number(input.value);
      } };
  }

  // Shows the server's per-field errors under the right fields.
  function showFieldErrors(fields, errors) {
    var shown = false;
    fields.forEach(function (f) {
      if (!f.err) return;
      var key = f.field.key;
      f.err.hidden = !(errors && errors[key]);
      f.err.textContent = (errors && errors[key]) || "";
      if (errors && errors[key]) shown = true;
    });
    return shown;
  }

  // Article titles are stored as Wikipedia paths ("Space_exploration"); show them as titles.
  function titleOf(path) { return (path || "").replace(/_/g, " "); }

  // ================================================================ settings (free play)

  function renderSettings(key) {
    stopPlay();
    findGame(key).then(function (g) {
      return api(gamePath(key, "/settings")).then(function (data) { drawSettings(g, data); });
    }).catch(showError);
  }

  function drawSettings(g, data) {
    var ctx = { gameKey: g.key };
    var platformFields = data.schema.platform.map(function (f) { return fieldInput(f, data.values.platform[f.key], "p"); });
    var gameFields = data.schema.game.map(function (f) {
      var v = data.values.game[f.key];
      return fieldInput(f, f.type === "article" ? titleOf(v) : v, "g", ctx);
    });
    var listField = gameFields.filter(function (f) { return f.field.type === "article_list"; })[0];
    ctx.listValue = listField ? listField.read : null;
    var saveBtn = el("button", { class: "primary", type: "submit", text: "Save settings" });
    var all = platformFields.concat(gameFields);
    var form = el("form", {
      onsubmit: function (e) {
        e.preventDefault();
        var body = { platform: {}, game: {} };
        platformFields.forEach(function (f) { body.platform[f.field.key] = f.read(); });
        gameFields.forEach(function (f) { body.game[f.field.key] = f.read(); });
        showFieldErrors(all, null);
        saveBtn.disabled = true;
        api(gamePath(g.key, "/settings"), { body: body }).then(function () {
          toast("Settings saved.");
          S.games = null;
        }).catch(function (err) {
          if (!showFieldErrors(all, err.fields)) toast(err.message);
        }).then(function () { saveBtn.disabled = false; });
      }
    }, [
      platformFields.length ? el("fieldset", {}, [el("legend", { text: "Rules" })].concat(platformFields.map(function (f) { return f.node; }))) : null,
      gameFields.length ? el("fieldset", {}, [el("legend", { text: "Game options" })].concat(gameFields.map(function (f) { return f.node; }))) : null,
      el("div", { class: "row" }, [saveBtn, el("a", { class: "button quiet", href: "#/", text: "Back to games" })])
    ]);
    var intro = g.type === "classroom"
      ? "These settings apply to everyone in your facility."
      : "Settings for free play, for everyone in your facility. Challenges have their own settings.";
    setView([pageHead([["Games", "#/"]], g.title + " settings", intro), form], { title: g.title });
  }

  // ================================================================ challenges (coaches)

  function renderChallenges(key) {
    stopPlay();
    findGame(key).then(function (g) {
      return api(gamePath(key, "/challenges")).then(function (data) { drawChallenges(g, data); });
    }).catch(showError);
  }

  function drawChallenges(g, data) {
    var head = pageHead([["Games", "#/"]], g.title + " challenges",
      "Set up " + g.title + " for a class, with its own settings and dates. Each challenge has its own scoreboard.",
      [el("a", { class: "button primary", href: "#/challenges/" + g.key + "/new", text: "New challenge" })]);
    if (!data.challenges.length) {
      setView([head, el("div", { class: "empty" }, [el("h2", { text: "No challenges yet" }),
        el("p", { text: data.classes.length ? "Make one for one of your classes." : "You need a class to set a challenge. Make one in Kolibri's Facility page." })])], { title: g.title });
      return;
    }
    var list = el("div", { class: "challenge-list" });
    data.challenges.forEach(function (c) {
      var base = g.key + "/c/" + c.id;
      list.appendChild(el("section", { class: "panel challenge-panel" }, [
        el("div", { class: "page-head compact" }, [
          el("div", {}, [
            el("span", { class: "tag " + c.state, text: { open: "Open", upcoming: "Coming up", closed: "Closed" }[c.state] }),
            el("h2", { text: c.title }),
            el("p", { class: "footnote", text: c.class_name + " · " + (c.counts === "first" ? "first attempt counts" : "best attempt counts") })
          ]),
          el("div", { class: "row" }, [
            el("a", { class: "button quiet", href: "#/board/" + base, text: "Scoreboard" }),
            el("a", { class: "button quiet", href: "#/results/" + base, text: "Results" }),
            el("a", { class: "button quiet", href: "#/play/" + base, text: "Try it" }),
            el("a", { class: "button quiet", href: "#/challenges/" + g.key + "/edit/" + c.id, text: "Edit" }),
            el("button", { class: "quiet danger", type: "button", text: "Delete", onclick: function () {
              if (!confirm("Delete the challenge \"" + c.title + "\"? Learners' attempts are kept, but its scoreboard goes away.")) return;
              api(gamePath(g.key, "/challenges/" + c.id + "/delete"), { body: {} })
                .then(function () { toast("Challenge deleted."); S.games = null; renderChallenges(g.key); })
                .catch(function (e) { toast(e.message); });
            } })
          ])
        ]),
        challengeFacts(g, c)
      ]));
    });
    setView([head, list], { title: g.title });
    // The shortest route is worked out in the background: check again shortly.
    if (data.challenges.some(function (c) { return c.best && c.best.status === "working"; })) {
      clearTimeout(drawChallenges.timer);
      drawChallenges.timer = setTimeout(function () {
        if (location.hash === "#/challenges/" + g.key) renderChallenges(g.key);
      }, 5000);
    }
  }

  function renderChallengeForm(key, challengeId) {
    stopPlay();
    findGame(key).then(function (g) {
      return api(gamePath(key, "/challenges")).then(function (data) {
        var c = challengeId ? data.challenges.filter(function (x) { return String(x.id) === String(challengeId); })[0] : null;
        if (challengeId && !c) throw new Error("That challenge doesn't exist any more.");
        drawChallengeForm(g, data, c);
      });
    }).catch(showError);
  }

  function drawChallengeForm(g, data, c) {
    var ctx = { gameKey: g.key };
    var now = new Date();
    var weekLater = new Date(now.getTime() + 7 * 24 * 3600 * 1000);
    var fields = [];

    var title = el("input", { id: "c-title", type: "text", value: c ? c.title : "", maxlength: "100", required: true });
    var classSel = el("select", { id: "c-class" }, data.classes.map(function (k) { return el("option", { value: k.id, text: k.name }); }));
    if (c) classSel.value = c.class_id;
    var opens = el("input", { id: "c-opens", type: "datetime-local", value: toLocalInput(c ? c.opens_at : now.toISOString()) });
    var closes = el("input", { id: "c-closes", type: "datetime-local", value: toLocalInput(c ? c.closes_at : weekLater.toISOString()) });
    var counts = el("select", { id: "c-counts" }, [
      el("option", { value: "first", text: "First attempt only (later attempts are practice)" }),
      el("option", { value: "best", text: "Best attempt" })
    ]);
    counts.value = c ? c.counts : ((g.scoring && g.scoring.counts) || "first");
    var limit = el("input", { id: "c-limit", type: "number", min: "0", max: "240", step: "1", value: String(c ? c.time_limit : 0) });

    function simple(key, label, input, help) {
      var err = el("div", { class: "err", hidden: true });
      fields.push({ field: { key: key }, err: err });
      return el("div", { class: "field" }, [el("label", { for: input.id, text: label }), help ? el("div", { class: "help", text: help }) : null, input, err]);
    }

    var saved = (c && c.settings) || {};
    var gameFields = data.schema.map(function (f) {
      var v = f.key in saved ? saved[f.key] : f["default"];
      if (f.type === "article") v = c && c[f.key] ? c[f.key] : titleOf(v);
      return fieldInput(f, v, "g", ctx);
    });
    var listField = gameFields.filter(function (f) { return f.field.type === "article_list"; })[0];
    ctx.listValue = listField ? listField.read : null;
    fields = fields.concat(gameFields);

    var saveBtn = el("button", { class: "primary", type: "submit", text: c ? "Save changes" : "Make challenge" });
    var form = el("form", {
      onsubmit: function (e) {
        e.preventDefault();
        var body = {
          title: title.value, class_id: classSel.value, counts: counts.value,
          time_limit: Number(limit.value || 0), opens_at: fromLocalInput(opens.value), closes_at: fromLocalInput(closes.value),
          settings: {}
        };
        gameFields.forEach(function (f) { body.settings[f.field.key] = f.read(); });
        showFieldErrors(fields, null);
        saveBtn.disabled = true;
        saveBtn.textContent = isRace(g) ? "Checking the articles…" : "Saving…";
        var path = c ? "/challenges/" + c.id : "/challenges";
        api(gamePath(g.key, path), { body: body }).then(function () {
          toast(c ? "Challenge saved." : "Challenge made.");
          S.games = null;
          location.hash = "#/challenges/" + g.key;
        }).catch(function (err) {
          if (!showFieldErrors(fields, err.fields)) toast(err.message);
          saveBtn.disabled = false;
          saveBtn.textContent = c ? "Save changes" : "Make challenge";
        });
      }
    }, [
      el("fieldset", {}, [
        el("legend", { text: "Challenge" }),
        simple("title", "Name", title, "Learners see this, for example \"Friday race: animals\"."),
        simple("class_id", "Class", classSel),
        simple("opens_at", "Opens", opens),
        simple("closes_at", "Closes", closes, "Scores and routes are shown to everyone after the challenge closes."),
        simple("counts", "Which attempt counts", counts),
        simple("time_limit", "Time limit in minutes (0 for none)", limit)
      ]),
      gameFields.length ? el("fieldset", {}, [el("legend", { text: "Game options" })].concat(gameFields.map(function (f) { return f.node; }))) : null,
      el("div", { class: "row" }, [saveBtn, el("a", { class: "button quiet", href: "#/challenges/" + g.key, text: "Cancel" })])
    ]);
    setView([pageHead([["Games", "#/"], ["Challenges", "#/challenges/" + g.key]], c ? "Change challenge" : "New " + g.title + " challenge",
      isRace(g) ? "Every learner gets the same start and goal. Leave them blank and one is picked at random." : null), form], { title: g.title });
  }

  // ================================================================ article lists (coaches)

  function raceGame() {
    return (S.games || []).filter(function (g) { return isRace(g) && g.playable; })[0] || null;
  }

  function renderLists() {
    stopPlay();
    loadGames().then(function () { return api("api/article-lists"); }).then(function (data) {
      var head = pageHead([["Games", "#/"]], "Article lists",
        "Lists of Wikipedia articles for Wiki BLAZE challenges. Learners can only visit articles in the chosen list.",
        [el("a", { class: "button primary", href: "#/lists/new", text: "New list" })]);
      if (!data.lists.length) {
        setView([head, el("div", { class: "empty" }, [el("h2", { text: "No lists yet" }),
          el("p", { text: "Wiki BLAZE comes with the Wikipedia for Schools list. Make your own to keep a challenge to one topic." })])], { title: "Article lists" });
        return;
      }
      var tbody = el("tbody");
      data.lists.forEach(function (l) {
        tbody.appendChild(el("tr", {}, [
          el("td", {}, [el("a", { href: "#/lists/" + l.id, text: l.name })]),
          el("td", { class: "num", text: String(l.count) }),
          el("td", { text: when(l.updated_at) })
        ]));
      });
      setView([head, el("div", { class: "panel" }, [el("table", {}, [
        el("thead", {}, [el("tr", {}, [el("th", { text: "Name" }), el("th", { class: "num", text: "Articles" }), el("th", { text: "Changed" })])]),
        tbody
      ])])], { title: "Article lists" });
    }).catch(showError);
  }

  function renderListForm(listId) {
    stopPlay();
    loadGames().then(function () {
      var game = raceGame();
      return listId ? api("api/article-lists/" + listId + q({ game: game ? game.key : null })) : null;
    }).then(function (data) { drawListForm(listId, data); }).catch(showError);
  }

  function drawListForm(listId, data) {
    var name = el("input", { id: "l-name", type: "text", maxlength: "100", value: data ? data.name : "" });
    var titles = el("textarea", { id: "l-titles", rows: "14", spellcheck: "false" });
    titles.value = data ? data.titles : "";
    var file = el("input", { id: "l-file", type: "file", accept: ".txt,.tsv,.csv,text/plain" });
    file.addEventListener("change", function () {
      if (!file.files.length) return;
      var reader = new FileReader();
      reader.onload = function () { titles.value = String(reader.result); };
      reader.readAsText(file.files[0]);
    });
    var errs = { name: el("div", { class: "err", hidden: true }), titles: el("div", { class: "err", hidden: true }) };
    var fields = [{ field: { key: "name" }, err: errs.name }, { field: { key: "titles" }, err: errs.titles }];
    var check = null;
    if (data && data.missing_count !== undefined) {
      check = el("div", { class: data.missing_count ? "notice" : "panel" }, [
        el("p", { text: plural(data.found, "article") + " found in the Wikipedia file." + (data.missing_count ? " " + plural(data.missing_count, "title") + " weren't found:" : "") }),
        data.missing_count ? el("p", { class: "missing", text: data.missing.join(", ") + (data.missing_count > data.missing.length ? ", …" : "") }) : null
      ]);
    }
    var saveBtn = el("button", { class: "primary", type: "submit", text: "Save list" });
    var form = el("form", {
      onsubmit: function (e) {
        e.preventDefault();
        showFieldErrors(fields, null);
        saveBtn.disabled = true;
        api("api/article-lists" + (listId ? "/" + listId : ""), { body: { name: name.value, titles: titles.value } }).then(function (saved) {
          toast("List saved.");
          location.hash = "#/lists/" + saved.id;
          if (String(saved.id) === String(listId)) renderListForm(listId);
        }).catch(function (err) {
          if (!showFieldErrors(fields, err.fields)) toast(err.message);
        }).then(function () { saveBtn.disabled = false; });
      }
    }, [
      el("fieldset", {}, [
        el("legend", { text: "List" }),
        el("div", { class: "field" }, [el("label", { for: "l-name", text: "Name" }), name, errs.name]),
        el("div", { class: "field wide" }, [
          el("label", { for: "l-titles", text: "Articles, one title per line" }),
          el("div", { class: "help", text: "Write titles as they appear on Wikipedia, like \"Solar System\" or \"Solar_System\". Lines starting with # are ignored." }),
          titles,
          el("div", { class: "help" }, ["Or load a text file: ", file]),
          errs.titles
        ])
      ]),
      el("div", { class: "row" }, [
        saveBtn,
        el("a", { class: "button quiet", href: "#/lists", text: "Back to lists" }),
        listId ? el("button", { class: "quiet danger", type: "button", text: "Delete list", onclick: function () {
          if (!confirm("Delete this list? Challenges that use it will need another list.")) return;
          api("api/article-lists/" + listId + "/delete", { body: {} }).then(function () { toast("List deleted."); location.hash = "#/lists"; })
            .catch(function (e) { toast(e.message); });
        } }) : null
      ])
    ]);
    setView([pageHead([["Games", "#/"], ["Article lists", "#/lists"]], listId ? (data ? data.name : "List") : "New article list"), check, form], { title: "Article lists" });
  }

  // ================================================================ Setup (administrators)

  function renderStatus() {
    stopPlay();
    loadGames().then(function () { return api("api/status"); }).then(drawStatus).catch(showError);
  }

  function drawStatus(data) {
    var parts = [pageHead([["Games", "#/"]], "Setup", "Install games, choose the Wikipedia file, and see anything that stops a game from working.")];
    if (data.can_install) parts.push(installPanel(data));
    parts.push(wikipediaPanel(data));

    var rows = el("tbody");
    data.games.forEach(function (g) {
      var actions = [];
      if (data.can_install && g.removable) {
        if (g.previous_version) actions.push(el("button", { class: "quiet", type: "button", text: "Go back to " + g.previous_version, onclick: function () {
          api(gamePath(g.key, "/restore"), { body: {} }).then(function (r) { toast("Now using version " + r.version + "."); S.games = null; renderStatus(); })
            .catch(function (e) { toast(e.message); });
        } }));
        actions.push(el("button", { class: "quiet danger", type: "button", text: "Remove", onclick: function () {
          if (!confirm("Remove " + g.title + " from this device? Learners' results are kept and come back if you install it again.")) return;
          api(gamePath(g.key, "/remove"), { body: {} }).then(function () { toast("Removed " + g.title + "."); S.games = null; renderStatus(); })
            .catch(function (e) { toast(e.message); });
        } }));
      }
      var from = { installed: "Installed", folder: "Game folder (for game makers)", channel: "Channel" }[g.origin] || g.origin;
      if (g.type === "classroom") from += " (Classroom Game, " + plural(g.content.resources.length, "resource") + ")";
      rows.appendChild(el("tr", {}, [
        el("td", {}, [g.title, g.playable ? el("span", { class: "tag ok", text: "ready" }) : el("span", { class: "tag warn", text: "can't play" })]),
        el("td", { text: g.version || "" }),
        el("td", { text: from }),
        el("td", {}, [el("code", { text: g.location }),
          g.problems.length ? el("ul", { class: "problems" }, g.problems.map(function (p) { return el("li", { text: p }); })) : null,
          (g.notes || []).length ? el("ul", { class: "notes" }, g.notes.map(function (p) { return el("li", { text: p }); })) : null]),
        el("td", {}, [el("div", { class: "row" }, actions)])
      ]));
    });
    parts.push(el("h2", { class: "section-title", text: "Games found (" + data.games.length + ")" }));
    parts.push(data.games.length
      ? el("div", { class: "panel" }, [el("table", {}, [
          el("thead", {}, [el("tr", {}, [el("th", { text: "Game" }), el("th", { text: "Version" }), el("th", { text: "From" }), el("th", { text: "File" }), el("th", { text: "" })])]),
          rows
        ])])
      : el("div", { class: "empty" }, [el("p", { text: "No games found yet." })]));
    parts.push(el("div", { class: "panel" }, [el("dl", { class: "kv" }, [
      el("dt", { text: "Plugin version" }), el("dd", { text: data.platform.version + " (game API " + data.platform.api + ")" }),
      el("dt", { text: "Games folder" }), el("dd", {}, data.local_dirs.map(function (d) { return el("div", {}, [el("code", { text: d })]); }))
    ])]));
    setView(parts, { title: "Setup" });
  }

  function installPanel(data) {
    var file = el("input", { id: "install-file", type: "file", accept: ".zip,application/zip" });
    var btn = el("button", { class: "primary", type: "submit", text: "Install" });
    var result = el("div", { class: "install-result", role: "status" });
    var form = el("form", {
      onsubmit: function (e) {
        e.preventDefault();
        if (!file.files.length) { toast("Choose a game's .zip file first."); return; }
        btn.disabled = true;
        btn.textContent = "Installing…";
        result.textContent = "";
        api("api/install", { raw: file.files[0] }).then(function (r) {
          var msg = (r.replaced ? "Updated " + r.game.title + " from " + r.replaced + " to " + r.game.version : "Installed " + r.game.title + " " + r.game.version) + ".";
          toast(msg);
          S.games = null;
          renderStatus();
        }).catch(function (err) {
          result.className = "install-result err";
          result.textContent = err.message;
          btn.disabled = false;
          btn.textContent = "Install";
        });
      }
    }, [
      el("div", { class: "field" }, [
        el("label", { for: "install-file", text: "Install or update a Free-play Game" }),
        el("div", { class: "help", text: "Choose the game's .zip file (at most " + data.max_upload_mb + " MB). Installing a newer version keeps the old one, so you can go back." }),
        file
      ]),
      el("div", { class: "row" }, [btn]),
      result
    ]);
    return el("section", { class: "panel setup-panel" }, [form]);
  }

  function wikipediaPanel(data) {
    var current = data.data_sources.wikipedia || "";
    var pick = el("select", { id: "wiki-pick" }, [el("option", { value: "", text: "None" })].concat(
      data.zim_files.map(function (z) { return el("option", { value: z.path, text: z.name + " (" + Math.round(z.size / 1048576) + " MB)" }); })
    ).concat([el("option", { value: "other", text: "Another file…" })]));
    var other = el("input", { id: "wiki-other", type: "text", placeholder: "/library/zims/content/wikipedia_en_....zim", value: "" });
    var known = data.zim_files.some(function (z) { return z.path === current; });
    pick.value = !current ? "" : known ? current : "other";
    other.value = known ? "" : current;
    var otherField = el("div", { class: "field", hidden: pick.value !== "other" }, [el("label", { for: "wiki-other", text: "Path of the .zim file" }), other]);
    pick.addEventListener("change", function () { otherField.hidden = pick.value !== "other"; });
    var btn = el("button", { class: "primary", type: "submit", text: "Save", disabled: !data.can_install });
    var form = el("form", {
      onsubmit: function (e) {
        e.preventDefault();
        var path = pick.value === "other" ? other.value.trim() : pick.value;
        btn.disabled = true;
        api("api/data-sources", { body: { name: "wikipedia", path: path } }).then(function () {
          toast(path ? "Wikipedia file saved." : "Wikipedia file cleared.");
          S.games = null;
          renderStatus();
        }).catch(function (err) { toast(err.message); btn.disabled = false; });
      }
    }, [
      el("div", { class: "field" }, [
        el("label", { for: "wiki-pick", text: "Wikipedia file for Wiki BLAZE" }),
        el("div", { class: "help", text: data.zim_files.length
          ? "These .zim files are on this device. Use an English Wikipedia file, ideally one that includes the Wikipedia for Schools articles."
          : "No .zim files were found in /library/zims/content. Type the path of a Wikipedia .zim file." }),
        pick
      ]),
      otherField,
      el("div", { class: "row" }, [btn])
    ]);
    return el("section", { class: "panel setup-panel" }, [form]);
  }

  // ================================================================ router

  function route() {
    var parts = location.hash.replace(/^#\/?/, "").split("/").map(decodeURIComponent);
    var name = parts[0], key = parts[1] || null;
    // ".../c/<id>" picks a challenge
    var challenge = parts[2] === "c" && parts[3] ? parts[3] : null;
    if (name === "play" && key) return renderPlay(key, challenge);
    if (name === "board" && key) return renderBoard(key, challenge);
    if (name === "results" && key) return renderResults(key, challenge);
    if (name === "settings" && key) return renderSettings(key);
    if (name === "challenges" && key) {
      if (parts[2] === "new") return renderChallengeForm(key, null);
      if (parts[2] === "edit" && parts[3]) return renderChallengeForm(key, parts[3]);
      return renderChallenges(key);
    }
    if (name === "scores" && key) return renderScores(key, parts[2] || null, parts[3] || null);
    if (name === "lists") {
      if (parts[1] === "new") return renderListForm(null);
      if (parts[1]) return renderListForm(parts[1]);
      return renderLists();
    }
    if (name === "status") return renderStatus();
    return renderLobby();
  }

  window.addEventListener("hashchange", route);
  route();
})();
