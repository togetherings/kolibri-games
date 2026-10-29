/* Kolibri Games shell: lobby, play, scoreboards and coach pages.
 * Plain JavaScript with no external libraries, so it works offline.
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

  var CSRF = document.querySelector('meta[name="csrf-token"]').content;
  var KOLIBRI_ROOT = document.querySelector('meta[name="kolibri-root"]').content || "/";
  var view = document.getElementById("view");
  var barMid = document.getElementById("bar-mid");
  var barEnd = document.getElementById("bar-end");

  var S = { me: null, platform: null, games: null, classes: null, play: null };

  // ---------------------------------------------------------------- utils

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

  function api(path, opts) {
    opts = opts || {};
    var init = { method: opts.method || "GET", credentials: "same-origin", headers: { Accept: "application/json" } };
    if (opts.body !== undefined) {
      init.method = opts.method || "POST";
      init.headers["Content-Type"] = "application/json";
      init.headers["X-CSRFToken"] = CSRF;
      init.body = JSON.stringify(opts.body);
    }
    return fetch(path, init).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (data) {
        if (!res.ok) {
          var err = new Error(data.message || "The server didn't answer (" + res.status + "). Check that Kolibri is running.");
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
    return d.toLocaleDateString(undefined, { day: "numeric", month: "short" }) + " " +
      d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
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

  function rulesNote(game, summary) {
    if (!game.scoring) return null;
    var counts = summary ? summary.counts : game.scoring.counts;
    if (counts === "first") {
      if (summary && summary.first_used) {
        return el("span", { class: "rule-note practice", text: "Your first attempt is done. Playing again is practice." });
      }
      return el("span", { class: "rule-note", text: "Your first attempt counts on the scoreboard." });
    }
    return el("span", { class: "rule-note", text: "Your best attempt counts on the scoreboard." });
  }

  // ---------------------------------------------------------------- lobby

  function renderLobby() {
    stopPlay();
    loadGames(true).then(function (games) {
      var head = el("div", { class: "page-head" }, [
        el("div", {}, [
          el("h1", { text: "Games" }),
          el("p", { text: games.length ? "Your results are saved to your Kolibri account." : "" })
        ])
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
        ? el("p", {}, ["Import a channel that contains games, or copy a game's .zim file into the local games folder. ",
            el("a", { href: "#/status", text: "See where games are loaded from" }), "."])
        : el("p", { text: "Ask your coach or administrator to add some." })
    ]);
  }

  function plural(n, word) {
    word = String(word || "").toLowerCase();
    return n + " " + (n === 1 ? word : word.replace(/y$/, "ie") + "s");
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
    if (S.me.role !== "learner") actions.push(el("a", { class: "button quiet", href: "#/settings/" + g.key, text: "Settings" }));
    return el("li", { class: "game" }, [
      el("img", { class: "game-icon", src: "api/games/" + g.key + "/icon", alt: "" }),
      el("div", {}, [
        el("h3", { text: g.title }),
        g.description ? el("p", { class: "desc", text: g.description }) : null,
        el("div", { class: "facts" }, facts)
      ]),
      el("div", { class: "row" }, actions)
    ]);
  }

  function gameCard(g) {
    if (g.type === "classroom" && g.playable) return classroomCard(g);
    var unplayable = !g.playable;
    var facts = [];
    var s = g.summary;
    if (s && g.scoring) {
      if (s.counted) {
        facts.push(el("span", {}, ["Your result ", el("b", { text: scoreText(g.scoring, s.counted.score) }), " in " + clock(s.counted.seconds)]));
      } else if (s.attempts && s.counts === "first") {
        facts.push(el("span", { text: "Your first attempt didn't finish" }));
      } else {
        facts.push(el("span", { text: s.attempts ? "No finished result yet" : "Not played yet" }));
      }
    } else if (s) {
      facts.push(el("span", { text: s.attempts ? "Played " + s.attempts + (s.attempts === 1 ? " time" : " times") : "Not played yet" }));
    }
    var actions = [];
    if (!unplayable) {
      actions.push(el("a", { class: "button primary", href: "#/play/" + g.key, text: "Play" }));
      if (g.scoring) actions.push(el("a", { class: "button quiet", href: "#/board/" + g.key, text: "Scoreboard" }));
    }
    if (S.me.role !== "learner" && g.id) {
      if (g.scoring) actions.push(el("a", { class: "button quiet", href: "#/results/" + g.key, text: "Results" }));
      actions.push(el("a", { class: "button quiet", href: "#/settings/" + g.key, text: "Settings" }));
    }
    return el("li", { class: "game" + (unplayable ? " unplayable" : "") }, [
      g.id ? el("img", { class: "game-icon", src: "api/games/" + g.key + "/icon", alt: "" }) : el("div", { class: "game-icon" }),
      el("div", {}, [
        el("h3", { text: g.title }),
        g.description ? el("p", { class: "desc", text: g.description }) : null,
        facts.length ? el("div", { class: "facts" }, facts) : null,
        !unplayable ? el("div", { class: "facts", style: "margin-top:.35rem" }, [rulesNote(g, s)]) : null,
        unplayable ? el("ul", { class: "problems" }, g.problems.map(function (p) { return el("li", { text: p }); })) : null
      ]),
      actions.length ? el("div", { class: "row" }, actions) : null
    ]);
  }

  // ----------------------------------------------------------------- play

  function stopPlay() {
    if (!S.play) return;
    clearInterval(S.play.timer);
    window.removeEventListener("message", S.play.listener);
    S.play = null;
  }

  function renderPlay(key) {
    stopPlay();
    var frameWrap = el("div", { class: "loading", text: "Opening the game…" });
    setView([frameWrap], { playing: true });
    Promise.all([loadGames(), api("api/games/" + encodeURIComponent(key))]).then(function (res) {
      var session = res[1];
      var play = {
        key: key,
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
      setView([play.frame], {
        playing: true,
        title: session.game.title,
        mid: [
          el("button", { class: "quiet", type: "button", text: "Back to games", onclick: function () { location.hash = "#/"; } }),
          el("span", { class: "play-title", text: session.game.title }),
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
    if (!s.game.scoring) { chip.hidden = true; return; }
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
        sendToGame(play, { kg: 1, event: "timeup" });
      }
    };
    tick();
    play.timer = setInterval(tick, 500);
  }

  function sendToGame(play, msg) {
    if (play.frame.contentWindow) play.frame.contentWindow.postMessage(msg, "*");
  }

  function gameApi(play, path) {
    return "api/games/" + encodeURIComponent(play.key) + path;
  }

  function needAttempt(play) {
    if (!play.attempt) {
      var err = new Error("Start the game first.");
      err.code = "no_attempt";
      throw err;
    }
    return play.attempt.id;
  }

  var METHODS = {
    hello: function (play) {
      var s = play.session;
      return {
        game: s.game,
        player: s.player,
        platform: s.platform,
        settings: s.settings,
        rules: s.rules,
        summary: s.summary,
        preview: false
      };
    },
    "attempt.start": function (play, params) {
      return api(gameApi(play, "/attempts"), { body: { resume: params.resume !== false } }).then(function (data) {
        play.attempt = data.attempt;
        updateRuleChip(play, data.attempt);
        startClock(play, data.time_limit, data.elapsed);
        return data;
      });
    },
    "attempt.event": function (play, params) {
      return api(gameApi(play, "/attempts/" + needAttempt(play) + "/events"), { body: { type: params.type, data: params.data } });
    },
    "attempt.finish": function (play, params) {
      return api(gameApi(play, "/attempts/" + needAttempt(play) + "/finish"), { body: params }).then(function (data) {
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
      return api(gameApi(play, "/attempts/" + id + "/abandon"), { body: {} });
    },
    "leaderboard.get": function (play) { return api(gameApi(play, "/leaderboard")); },
    "results.mine": function (play) { return api(gameApi(play, "/mine")); },
    "state.get": function (play) { return api(gameApi(play, "/state")).then(function (d) { return d.data; }); },
    "state.set": function (play, params) { return api(gameApi(play, "/state"), { body: { data: params.data } }); },
    call: function (play, params) { return api(gameApi(play, "/call"), { body: { method: params.method, params: params.params } }); },
    exit: function () { setTimeout(function () { location.hash = "#/"; }, 0); return { ok: true }; }
  };

  function handleGameMessage(play, e) {
    // Only accept messages from this game's own frame.
    if (!play.frame || e.source !== play.frame.contentWindow) return;
    var msg = e.data;
    if (!msg || msg.kg !== 1 || typeof msg.method !== "string" || typeof msg.id !== "number") return;
    var fn = METHODS[msg.method];
    var reply = function (payload) { sendToGame(play, Object.assign({ kg: 1, id: msg.id }, payload)); };
    if (!fn) {
      reply({ error: { code: "unknown_method", message: "Kolibri Games doesn't know '" + msg.method + "'." } });
      return;
    }
    Promise.resolve().then(function () { return fn(play, msg.params || {}); }).then(
      function (result) { reply({ result: result === undefined ? null : result }); },
      function (err) {
        if (err.code === "time_up") {
          play.attempt = null;
          sendToGame(play, { kg: 1, event: "timeup" });
        }
        reply({ error: { code: err.code || "error", message: err.message } });
      }
    );
  }

  // ------------------------------------------------- Free-play scoreboard

  function classPicker(selected, onChange, allowEveryone) {
    return loadClasses().then(function (data) {
      if (!data.classes.length && !data.whole_facility) return null;
      var select = el("select", { "aria-label": "Class", onchange: function () { onChange(select.value); } });
      if (data.whole_facility && allowEveryone) select.appendChild(el("option", { value: "", text: "Everyone" }));
      data.classes.forEach(function (c) { select.appendChild(el("option", { value: c.id, text: c.name })); });
      if (selected) select.value = selected;
      return select;
    });
  }

  function renderBoard(key, classId) {
    stopPlay();
    findGame(key).then(function (g) {
      var q = classId ? "?class=" + encodeURIComponent(classId) : "";
      return Promise.all([
        api("api/games/" + encodeURIComponent(key) + "/leaderboard" + q),
        S.me.role !== "learner" ? classPicker(classId, function (v) { renderBoard(key, v); }, true) : null
      ]).then(function (res) {
        var data = res[0], picker = res[1];
        var head = el("div", { class: "page-head" }, [
          el("div", {}, [
            el("a", { class: "crumb", href: "#/", text: "Games" }),
            el("h1", { text: g.title + " scoreboard" }),
            el("p", { text: data.counts === "first" ? "Each player's first attempt." : "Each player's best attempt." })
          ]),
          el("div", { class: "row" }, [picker, el("a", { class: "button primary", href: "#/play/" + key, text: "Play" })])
        ]);
        var body;
        if (!data.rows.length) {
          body = el("div", { class: "empty" }, [el("h2", { text: "No results yet" }), el("p", { text: "Be the first to finish." })]);
        } else {
          body = el("div", { class: "panel" }, [boardTable(g, data.rows)]);
        }
        var notes = [];
        if (data.visibility === "hidden") notes.push("Your coach has hidden other players' results.");
        if (data.visibility === "initials") notes.push("Other players are shown by their initials.");
        if (!g.validator) notes.push("This game reports its own scores, so they aren't checked by the server.");
        setView([head, body].concat(notes.map(function (n) { return el("p", { class: "footnote", text: n }); })), { title: g.title });
      });
    }).catch(showError);
  }

  function boardTable(g, rows) {
    var label = (g.scoring && g.scoring.label) || "Score";
    var tbody = el("tbody");
    rows.forEach(function (r) {
      tbody.appendChild(el("tr", { class: r.me ? "me" : "" }, [
        el("td", {}, [el("span", { class: "rank r" + r.rank, text: String(r.rank) })]),
        el("td", { text: r.name + (r.me ? " (you)" : "") }),
        el("td", { class: "num", text: scoreText(g.scoring, r.score) }),
        el("td", { class: "num", text: clock(r.seconds) })
      ]));
    });
    return el("table", {}, [
      el("thead", {}, [el("tr", {}, [el("th", { text: "Rank" }), el("th", { text: "Name" }),
        el("th", { class: "num", text: label }), el("th", { class: "num", text: "Time" })])]),
      tbody
    ]);
  }

  // ----------------------------------------------------------- scoreboards

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
      var q = classId ? "?class=" + encodeURIComponent(classId) : "";
      return Promise.all([
        api("api/games/" + encodeURIComponent(key) + "/scoreboards" + q),
        S.me.role !== "learner" ? classPicker(classId, function (v) { renderScores(key, boardId, v); }, true) : null
      ]).then(function (res) { drawScores(g, res[0], res[1], boardId, classId); });
    }).catch(showError);
  }

  function drawScores(g, data, picker, boardId, classId) {
    var spec = data.spec;
    var coach = S.me.role !== "learner";
    var csv = "api/games/" + encodeURIComponent(g.key) + "/scoreboards?format=csv" + (classId ? "&class=" + encodeURIComponent(classId) : "");
    var head = el("div", { class: "page-head" }, [
      el("div", {}, [
        el("a", { class: "crumb", href: "#/", text: "Games" }),
        el("h1", { text: g.title + " scoreboard" }),
        el("p", { text: "Scores from playing " + g.title + " in Learn. Each learner's best result counts." })
      ]),
      el("div", { class: "row" }, [picker, coach && data.boards.length ? el("a", { class: "button", href: csv, text: "Download CSV" }) : null])
    ]);
    var notes = [];
    if (data.visibility === "hidden") notes.push("Your coach has hidden other players' results.");
    if (data.visibility === "initials") notes.push("Other players are shown by their initials.");
    notes.push("These scores come from the game itself, so the server doesn't check them.");
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

  function rankWord(rank) {
    var n = rank % 100, s = n > 10 && n < 14 ? "th" : ({ 1: "st", 2: "nd", 3: "rd" }[rank % 10] || "th");
    return rank + s;
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

  // --------------------------------------------------------------- results

  function renderResults(key, classId) {
    stopPlay();
    findGame(key).then(function (g) {
      return loadClasses().then(function (classes) {
        if (!classes.whole_facility && !classId && classes.classes.length) classId = classes.classes[0].id;
        var q = classId ? "?class=" + encodeURIComponent(classId) : "";
        return Promise.all([
          api("api/games/" + encodeURIComponent(key) + "/results" + q),
          classPicker(classId, function (v) { renderResults(key, v); }, true)
        ]).then(function (res) { drawResults(g, res[0], res[1], classId); });
      });
    }).catch(showError);
  }

  function drawResults(g, data, picker, classId) {
    var key = g.key;
    var csv = "api/games/" + encodeURIComponent(key) + "/results?format=csv" + (classId ? "&class=" + encodeURIComponent(classId) : "");
    var head = el("div", { class: "page-head" }, [
      el("div", {}, [
        el("a", { class: "crumb", href: "#/", text: "Games" }),
        el("h1", { text: g.title + " results" }),
        el("p", { text: data.counts === "first"
          ? "The counted result is each learner's first attempt. Later attempts are practice."
          : "The counted result is each learner's best attempt." })
      ]),
      el("div", { class: "row" }, [picker, el("a", { class: "button", href: csv, text: "Download CSV" })])
    ]);
    if (!data.rows.length) {
      setView([head, el("div", { class: "empty" }, [el("h2", { text: "Nobody has played yet" }),
        el("p", { text: classId ? "No one in this class has played this game." : "Results appear here once learners play." })])], { title: g.title });
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
          if (!confirm("Reset " + r.name + "'s results for " + g.title + "? Their attempts are kept for your records, but their next attempt will count as their first.")) return;
          api("api/games/" + encodeURIComponent(key) + "/results/" + r.user_id + "/reset", { body: {} })
            .then(function () { toast("Reset " + r.name + "."); renderResults(key, classId); })
            .catch(function (e) { toast(e.message); });
        } });
      tbody.appendChild(el("tr", {}, [
        el("td", {}, [r.rank ? el("span", { class: "rank r" + r.rank, text: String(r.rank) }) : ""]),
        el("td", { text: r.name }),
        el("td", { class: "num" }, counted
          ? [scoreText(g.scoring, counted.score), counted.verified ? null : el("span", { class: "tag warn", text: "unchecked" })]
          : [r.attempts ? "Didn't finish" : "Not played"]),
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
    setView([head, el("div", { class: "panel" }, [table]),
      !g.validator ? el("p", { class: "footnote", text: "This game reports its own scores, so results marked \"unchecked\" weren't verified by the server." }) : null
    ], { title: g.title });
  }

  function historyList(g, r) {
    var list = el("ol");
    r.history.forEach(function (a) {
      var bits = ["Attempt " + a.number + ": "];
      if (a.status === "finished") bits.push(scoreText(g.scoring, a.score) + " in " + clock(a.seconds));
      else bits.push({ started: "in progress", abandoned: "left without finishing", expired: "ran out of time" }[a.status] || a.status);
      var details = el("details", {}, [
        el("summary", { text: "Moves and details" }),
        el("pre", { class: "detail", text: JSON.stringify({ detail: a.detail, moves: a.events }, null, 1) })
      ]);
      list.appendChild(el("li", {}, [
        bits.join(""),
        a.practice ? el("span", { class: "tag", text: "practice" }) : null,
        el("span", { class: "footnote", text: "  " + when(a.started_at) }),
        (a.events && a.events.length) || (a.detail && Object.keys(a.detail).length) ? details : null
      ]));
    });
    if (r.reset_attempts) list.appendChild(el("li", { class: "footnote", text: r.reset_attempts + " earlier attempt(s) were reset." }));
    return list;
  }

  // -------------------------------------------------------------- settings

  function renderSettings(key) {
    stopPlay();
    findGame(key).then(function (g) {
      return api("api/games/" + encodeURIComponent(key) + "/settings").then(function (data) {
        drawSettings(g, data);
      });
    }).catch(showError);
  }

  function fieldInput(field, value, group) {
    var id = "f-" + group + "-" + field.key;
    var input;
    if (field.type === "boolean") {
      input = el("input", { id: id, type: "checkbox", checked: !!value });
      return { node: el("div", { class: "field check" }, [input, el("label", { for: id, text: field.label })]), input: input, field: field };
    }
    if (field.type === "choice") {
      input = el("select", { id: id });
      field.choices.forEach(function (c, i) {
        input.appendChild(el("option", { value: String(i), text: c.label }));
        if (c.value === value) input.value = String(i);
      });
    } else {
      input = el("input", {
        id: id,
        type: field.type === "text" ? "text" : "number",
        value: value === null || value === undefined ? "" : String(value),
        min: field.min, max: field.max,
        step: field.type === "integer" ? "1" : field.type === "number" ? "any" : null
      });
    }
    var err = el("div", { class: "err", hidden: true });
    return {
      node: el("div", { class: "field" }, [el("label", { for: id, text: field.label }), field.help ? el("div", { class: "help", text: field.help }) : null, input, err]),
      input: input, field: field, err: err
    };
  }

  function readInput(f) {
    if (f.field.type === "boolean") return f.input.checked;
    if (f.field.type === "choice") return f.field.choices[Number(f.input.value)].value;
    if (f.field.type === "text") return f.input.value;
    return f.input.value === "" ? null : Number(f.input.value);
  }

  function drawSettings(g, data) {
    var platformFields = data.schema.platform.map(function (f) { return fieldInput(f, data.values.platform[f.key], "p"); });
    var gameFields = data.schema.game.map(function (f) { return fieldInput(f, data.values.game[f.key], "g"); });
    var saveBtn = el("button", { class: "primary", type: "submit", text: "Save settings" });
    var form = el("form", {
      onsubmit: function (e) {
        e.preventDefault();
        var body = { platform: {}, game: {} };
        platformFields.forEach(function (f) { body.platform[f.field.key] = readInput(f); if (f.err) f.err.hidden = true; });
        gameFields.forEach(function (f) { body.game[f.field.key] = readInput(f); if (f.err) f.err.hidden = true; });
        saveBtn.disabled = true;
        api("api/games/" + encodeURIComponent(g.key) + "/settings", { body: body }).then(function () {
          toast("Settings saved.");
          S.games = null;
        }).catch(function (err) {
          var fields = err.fields || {};
          platformFields.concat(gameFields).forEach(function (f) {
            if (fields[f.field.key] && f.err) { f.err.textContent = fields[f.field.key]; f.err.hidden = false; }
          });
          if (!err.fields) toast(err.message);
        }).then(function () { saveBtn.disabled = false; });
      }
    }, [
      el("fieldset", {}, [el("legend", { text: "Rules" })].concat(platformFields.map(function (f) { return f.node; }))),
      gameFields.length ? el("fieldset", {}, [el("legend", { text: "Game options" })].concat(gameFields.map(function (f) { return f.node; }))) : null,
      el("div", { class: "row" }, [saveBtn, el("a", { class: "button quiet", href: "#/", text: "Back to games" })])
    ]);
    setView([
      el("div", { class: "page-head" }, [el("div", {}, [
        el("a", { class: "crumb", href: "#/", text: "Games" }),
        el("h1", { text: g.title + " settings" }),
        el("p", { text: g.type === "classroom"
          ? "These settings apply to everyone in your facility."
          : "These settings apply to everyone in your facility. Changes apply to attempts started after you save." })
      ])]),
      form
    ], { title: g.title });
  }

  // ---------------------------------------------------------------- status

  function renderStatus() {
    stopPlay();
    loadGames().then(function () { return api("api/status"); }).then(function (data) {
      var rows = el("tbody");
      data.games.forEach(function (g) {
        rows.appendChild(el("tr", {}, [
          el("td", {}, [g.title, g.playable ? el("span", { class: "tag ok", text: "ready" }) : el("span", { class: "tag warn", text: "can't play" })]),
          el("td", { text: (g.version || "") }),
          el("td", { text: (g.origin === "channel" ? "Channel" : "Local folder") + (g.type === "classroom" ? " (Classroom Game, " + plural(g.content.resources.length, "resource") + ")" : "") }),
          el("td", {}, [el("code", { text: g.location }),
            g.problems.length ? el("ul", { class: "problems" }, g.problems.map(function (p) { return el("li", { text: p }); })) : null])
        ]));
      });
      var sources = Object.keys(data.data_sources);
      setView([
        el("div", { class: "page-head" }, [el("div", {}, [
          el("a", { class: "crumb", href: "#/", text: "Games" }),
          el("h1", { text: "Setup" }),
          el("p", { text: "Where this device finds games, and anything that stops them from working." })
        ])]),
        el("div", { class: "panel" }, [el("dl", { class: "kv" }, [
          el("dt", { text: "Plugin version" }), el("dd", { text: data.platform.version + " (game API " + data.platform.api + ")" }),
          el("dt", { text: "Local game folders" }), el("dd", {}, data.local_dirs.map(function (d) { return el("div", {}, [el("code", { text: d })]); })),
          el("dt", { text: "Rule checkers" }), el("dd", { text: data.validators.join(", ") || "None" }),
          el("dt", { text: "Data sources" }), el("dd", {}, sources.length
            ? sources.map(function (s) { return el("div", {}, [s + " = ", el("code", { text: data.data_sources[s] })]); })
            : ["None. Add them to ", el("code", { text: data.data_sources_file })])
        ])]),
        el("h2", { style: "margin:1.5rem 0 .75rem;font-size:1.2rem", text: "Games found (" + data.games.length + ")" }),
        data.games.length
          ? el("div", { class: "panel" }, [el("table", {}, [
              el("thead", {}, [el("tr", {}, [el("th", { text: "Game" }), el("th", { text: "Version" }), el("th", { text: "From" }), el("th", { text: "File" })])]),
              rows
            ])])
          : el("div", { class: "empty" }, [el("p", { text: "No games found. Import a channel with games, or copy a game .zim into one of the local game folders above." })])
      ], { title: "Setup" });
    }).catch(showError);
  }

  // ---------------------------------------------------------------- router

  function route() {
    var parts = location.hash.replace(/^#\/?/, "").split("/");
    var name = parts[0], key = parts[1] ? decodeURIComponent(parts[1]) : null;
    if (name === "play" && key) return renderPlay(key);
    if (name === "board" && key) return renderBoard(key);
    if (name === "scores" && key) return renderScores(key, parts[2] ? decodeURIComponent(parts[2]) : null, parts[3] || null);
    if (name === "results" && key) return renderResults(key);
    if (name === "settings" && key) return renderSettings(key);
    if (name === "status") return renderStatus();
    return renderLobby();
  }

  window.addEventListener("hashchange", route);
  route();
})();
