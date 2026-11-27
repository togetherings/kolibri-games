/* Smoke Signals (Sketches Morph Oddly, Kindling Excitement).
 *
 * The Kolibri Games server keeps the rooms: who's playing, whose turn it is,
 * the time left, and every prompt, drawing and guess (see the plugin's
 * smokesignals.py and docs/SMOKE_SIGNALS.md). This page asks it for news
 * every two seconds and shows what the player has to do:
 *
 *   KolibriGames.move("create", {speed, rounds})   start a new game (you're the host)
 *   KolibriGames.move("join", {code})              join one
 *   KolibriGames.move("poll", {have})              news: the room, and this player's task
 *   KolibriGames.move("submit", {step, text})      a prompt or a guess
 *   KolibriGames.move("submit", {step, drawing})   a drawing: {strokes: [[colour, size, x, y, x, y, ...]]}
 *   KolibriGames.move("begin" | "skip" | "end" | "remove" | "leave")   the host's buttons, and leaving
 *   KolibriGames.move("chains") / move("chain", {index})   every chain at the end
 *
 * Drawings are kept as lines, not pictures: small to send, and sharp on any screen.
 */
(function () {
  "use strict";
  var KG = window.KolibriGames;
  var $ = function (id) { return document.getElementById(id); };

  // The same as the server's smokesignals.py.
  var WIDTH = 800, HEIGHT = 600;
  var PALETTE = ["#1f1b16", "#d62828", "#f77f00", "#fcbf49", "#2a9d8f", "#1d4ed8", "#7b2cbf", "#8d5524", "#ffffff"];
  var COLOUR_NAMES = ["Black", "Red", "Orange", "Yellow", "Green", "Blue", "Purple", "Brown", "Eraser"];
  var SIZES = [4, 10, 24];
  var SIZE_NAMES = ["Thin", "Medium", "Thick"];
  var MAX_POINTS = 6000;
  var POLL_MS = 2000;
  var SCREENS = ["lobby", "waiting-room", "prompt", "draw", "guess", "wait", "reveal"];

  var S = {
    info: null,
    view: null,
    busy: false,
    poll: null,
    task: null,          // the task on screen: {key, kind, step, text | drawing | suggestions}
    deadline: null,      // when this step's time runs out, by this device's clock
    timer: null,
    autoSent: null,      // the task key handed in when time ran out
    strokes: [],         // the drawing in progress
    history: [],         // for Undo: earlier versions of strokes
    colour: 0,
    size: 1,
    chains: null,
    chain: null,         // the chain being shown at the end
    shown: 0,            // how many of its entries are showing
    drawn: 0,            // how many were showing before (only new ones rise into view)
    confirm: null        // a button waiting for its second click
  };

  // ------------------------------------------------------------------ helpers

  function show(id) {
    SCREENS.forEach(function (s) { $(s).hidden = s !== id; });
    var room = S.view && S.view.room;
    $("bar").hidden = !room || room.status !== "playing";
    $("host-tools").hidden = !room || room.status !== "playing";
    if (room) $("btn-end").hidden = !room.host;
  }

  function error(text) {
    $("error").textContent = text || "";
    $("error").hidden = !text;
  }

  function notice(text) {
    $("notice").textContent = text || "";
    $("notice").hidden = !text;
  }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  function plural(n, word) { return n + " " + word + (n === 1 ? "" : "s"); }

  function names(list) {
    if (list.length <= 1) return list.join("");
    return list.slice(0, -1).join(", ") + " and " + list[list.length - 1];
  }

  // A button that needs a second click (pop-ups don't work in the games page's frame).
  function twice(button, question, action) {
    var label = button.textContent;
    button.addEventListener("click", function () {
      if (S.confirm !== button) {
        if (S.confirm) S.confirm.reset();
        S.confirm = button;
        button.textContent = question;
        button.classList.add("confirm");
        button.reset = function () { button.textContent = label; button.classList.remove("confirm"); S.confirm = null; };
        setTimeout(function () { if (S.confirm === button) button.reset(); }, 4000);
        return;
      }
      button.reset();
      action();
    });
  }

  function send(kind, data) {
    if (S.busy && kind !== "poll") return Promise.resolve(null);
    if (kind !== "poll") S.busy = true;
    document.body.classList.toggle("busy", kind !== "poll");
    return KG.move(kind, data || {}).then(function (reply) {
      if (kind !== "poll") error("");
      return reply;
    }, function (e) {
      if (kind !== "poll" || e.code !== "timeout") error(e.message);
      return null;
    }).then(function (reply) {
      if (kind !== "poll") { S.busy = false; document.body.classList.remove("busy"); }
      return reply;
    });
  }

  // ------------------------------------------------------------------ news from the server

  function startPolling() {
    clearInterval(S.poll);
    S.poll = setInterval(function () {
      if (S.busy) return;
      send("poll", { have: S.task && S.task.key }).then(function (view) { if (view) render(view); });
    }, POLL_MS);
  }

  function render(view) {
    S.view = view;
    if (view.notice) notice(view.notice);
    var room = view.room;
    if (!room) { S.task = null; stopTimer(); return renderLobby(view); }
    notice("");
    if (room.status === "lobby") return renderWaitingRoom(room);
    if (room.status === "done") { stopTimer(); return renderReveal(room); }
    if (room.status === "playing") return renderPlaying(room, view.task);
    renderLobby({ rooms: [], can_host: true });
  }

  // ------------------------------------------------------------------ lobby

  function renderLobby(view) {
    S.chains = null;
    $("host-panel").hidden = !view.can_host;
    $("host-note").hidden = view.can_host;
    var list = $("rooms");
    list.innerHTML = "";
    (view.rooms || []).forEach(function (r) {
      var li = el("li");
      var b = el("button", "room");
      b.type = "button";
      b.appendChild(el("b", "", r.code));
      b.appendChild(el("span", "", r.host + "'s game · " + plural(r.players, "player")));
      b.addEventListener("click", function () { join(r.code); });
      li.appendChild(b);
      list.appendChild(li);
    });
    if (!(view.rooms || []).length) list.appendChild(el("li", "note", "No games are waiting for players. Start one, or type a code."));
    show("lobby");
  }

  function join(code) {
    send("join", { code: code }).then(function (view) { if (view) render(view); });
  }

  // ------------------------------------------------------------------ waiting room

  function renderWaitingRoom(room) {
    $("room-code").textContent = room.code;
    var n = room.players.length;
    var lead = n < room.min_players
      ? "Waiting for players. Smoke Signals needs at least " + room.min_players + "."
      : plural(n, "player") + " ready. " + (room.host ? "Start when everyone's here." : "The host starts the game.");
    $("room-lead").textContent = lead + " Tell others the code so they can join.";
    var list = $("room-players");
    list.innerHTML = "";
    room.players.forEach(function (p, i) {
      var li = el("li", p.me ? "me" : "");
      li.appendChild(el("span", "", p.name + (p.me ? " (you)" : "")));
      if (p.host) li.appendChild(el("span", "tag", "host"));
      if (p.away) li.appendChild(el("span", "tag away", "away"));
      if (room.host && !p.me) {
        var b = el("button", "quiet small", "Remove");
        b.type = "button";
        twice(b, "Remove " + p.name + "?", function () {
          send("remove", { seat: i }).then(function (view) { if (view) render(view); });
        });
        li.appendChild(b);
      }
      list.appendChild(li);
    });
    $("btn-begin").hidden = !room.host;
    $("btn-begin").disabled = n < room.min_players;
    show("waiting-room");
  }

  // ------------------------------------------------------------------ playing

  function stepText(room, task) {
    var round = Math.ceil(task.step / 2);
    if (task.kind === "prompt") return "Writing";
    return (task.kind === "draw" ? "Drawing" : "Guessing") + ", round " + round + " of " + room.rounds;
  }

  function renderPlaying(room, task) {
    $("bar-code").textContent = room.code;
    if (!task) return show("wait");
    $("bar-step").textContent = stepText(room, task);
    setTimer(task);
    if (task.done) {
      var waiting = task.waiting || [];
      $("wait-lead").textContent = waiting.length
        ? "Waiting for " + names(waiting) + "."
        : "Passing everything on…";
      $("btn-skip").hidden = !room.host || !waiting.length;
      return show("wait");
    }
    if (!S.task || S.task.key !== task.key) startTask(task);
    show(task.kind);
  }

  function startTask(task) {
    S.task = task;
    S.autoSent = null;
    if (task.kind === "prompt") {
      $("prompt-text").value = "";
      $("prompt-write").hidden = task.typing === false;
      $("prompt-lead").textContent = task.typing === false
        ? "Pick one of these for the next player to draw."
        : "The next player will draw it. Keep it short, or pick an idea.";
      showIdeas(task.suggestions || []);
      setTimeout(function () { if (task.typing !== false) $("prompt-text").focus(); }, 50);
    } else if (task.kind === "draw") {
      $("draw-what").textContent = task.text || "anything you like";
      S.strokes = [];
      S.history = [];
      redraw();
    } else {
      $("guess-text").value = "";
      $("guess-nothing").hidden = !!task.drawing;
      paint($("guess-canvas"), task.drawing ? task.drawing.strokes : []);
      setTimeout(function () { $("guess-text").focus(); }, 50);
    }
  }

  function showIdeas(ideas) {
    var box = $("ideas");
    box.innerHTML = "";
    ideas.forEach(function (idea) {
      var b = el("button", "idea", idea);
      b.type = "button";
      b.addEventListener("click", function () {
        if (S.task && S.task.typing === false) handIn({ text: idea });
        else { $("prompt-text").value = idea; $("prompt-text").focus(); }
      });
      box.appendChild(b);
    });
  }

  function handIn(data, auto) {
    if (!S.task) return Promise.resolve();
    var key = S.task.key;
    if (auto) S.autoSent = key;
    data.step = S.task.step;
    return send("submit", data).then(function (view) {
      if (view) render(view);
      else if (auto) S.autoSent = key;
    });
  }

  function handInText(input) {
    var text = $(input).value.trim();
    if (!text) { error("Write a few words first."); $(input).focus(); return; }
    handIn({ text: text });
  }

  // ------------------------------------------------------------------ the timer

  function setTimer(task) {
    if (task.seconds_left === null || task.seconds_left === undefined || task.done) {
      stopTimer();
      return;
    }
    var deadline = Date.now() + task.seconds_left * 1000;
    // Keep this device's countdown smooth: only follow the server when they disagree by more than 2 seconds.
    if (!S.deadline || Math.abs(deadline - S.deadline) > 2000) S.deadline = deadline;
    if (!S.timer) S.timer = setInterval(tick, 250);
    tick();
  }

  function stopTimer() {
    clearInterval(S.timer);
    S.timer = null;
    S.deadline = null;
    $("bar-timer").hidden = true;
  }

  function tick() {
    if (!S.deadline) return;
    var left = Math.max(0, Math.ceil((S.deadline - Date.now()) / 1000));
    var t = $("bar-timer");
    t.hidden = false;
    t.textContent = left ? Math.floor(left / 60) + ":" + (left % 60 < 10 ? "0" : "") + (left % 60) : "Time's up";
    t.className = "timer" + (left <= 10 ? " low" : "");
    if (left === 0 && S.task && S.autoSent !== S.task.key && S.view && S.view.task && !S.view.task.done) {
      // Hand in what's there. An empty prompt or guess is left for the server to fill in.
      S.autoSent = S.task.key;
      if (S.task.kind === "draw") handIn({ drawing: { strokes: S.strokes } }, true);
      else {
        var text = $(S.task.kind === "prompt" ? "prompt-text" : "guess-text").value.trim();
        if (text) handIn({ text: text }, true);
      }
    }
  }

  // ------------------------------------------------------------------ drawing

  // Draw lines on a canvas that is 800 x 600 drawing units inside.
  function paint(canvas, strokes) {
    var ctx = canvas.getContext("2d");
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    var scale = canvas.width / WIDTH;
    (strokes || []).forEach(function (s) { line(ctx, s, scale, 0, 0); });
  }

  function line(ctx, s, scale, ox, oy) {
    ctx.strokeStyle = ctx.fillStyle = PALETTE[s[0]];
    ctx.lineWidth = SIZES[s[1]] * scale;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    if (s.length === 4) {
      ctx.beginPath();
      ctx.arc(ox + s[2] * scale, oy + s[3] * scale, ctx.lineWidth / 2, 0, Math.PI * 2);
      ctx.fill();
      return;
    }
    ctx.beginPath();
    ctx.moveTo(ox + s[2] * scale, oy + s[3] * scale);
    for (var i = 4; i < s.length; i += 2) ctx.lineTo(ox + s[i] * scale, oy + s[i + 1] * scale);
    ctx.stroke();
  }

  function redraw() { paint($("canvas"), S.strokes); }

  function points() {
    return S.strokes.reduce(function (n, s) { return n + (s.length - 2) / 2; }, 0);
  }

  function setUpCanvas() {
    var canvas = $("canvas");
    var current = null;
    function at(e) {
      var r = canvas.getBoundingClientRect();
      return [
        Math.max(0, Math.min(WIDTH, Math.round((e.clientX - r.left) / r.width * WIDTH))),
        Math.max(0, Math.min(HEIGHT, Math.round((e.clientY - r.top) / r.height * HEIGHT)))
      ];
    }
    canvas.addEventListener("pointerdown", function (e) {
      if (points() >= MAX_POINTS) { error("That's plenty of detail! Undo some lines to draw more."); return; }
      e.preventDefault();
      canvas.setPointerCapture(e.pointerId);
      var p = at(e);
      S.history.push(S.strokes.slice());
      current = [S.colour, S.size, p[0], p[1]];
      S.strokes.push(current);
      redraw();
    });
    canvas.addEventListener("pointermove", function (e) {
      if (!current) return;
      var p = at(e);
      var lx = current[current.length - 2], ly = current[current.length - 1];
      if (Math.abs(p[0] - lx) + Math.abs(p[1] - ly) < 4 || points() >= MAX_POINTS) return;
      current.push(p[0], p[1]);
      var ctx = canvas.getContext("2d");
      line(ctx, [current[0], current[1], lx, ly, p[0], p[1]], canvas.width / WIDTH, 0, 0);
    });
    var end = function () { current = null; };
    canvas.addEventListener("pointerup", end);
    canvas.addEventListener("pointercancel", end);

    PALETTE.forEach(function (c, i) {
      var b = el("button", "swatch" + (i === PALETTE.length - 1 ? " eraser" : ""));
      b.type = "button";
      b.style.background = c;
      b.setAttribute("role", "radio");
      b.setAttribute("aria-label", COLOUR_NAMES[i]);
      b.title = COLOUR_NAMES[i];
      b.addEventListener("click", function () { S.colour = i; markTools(); });
      $("palette").appendChild(b);
    });
    SIZES.forEach(function (size, i) {
      var b = el("button", "size");
      b.type = "button";
      b.setAttribute("role", "radio");
      b.setAttribute("aria-label", SIZE_NAMES[i]);
      b.title = SIZE_NAMES[i];
      var dot = el("i");
      dot.style.width = dot.style.height = Math.max(6, size) + "px";
      b.appendChild(dot);
      b.addEventListener("click", function () { S.size = i; markTools(); });
      $("sizes").appendChild(b);
    });
    markTools();
    $("btn-undo").addEventListener("click", function () {
      if (S.history.length) { S.strokes = S.history.pop(); redraw(); }
    });
    $("btn-clear").addEventListener("click", function () {
      if (!S.strokes.length) return;
      S.history.push(S.strokes.slice());
      S.strokes = [];
      redraw();
    });
    $("btn-drawn").addEventListener("click", function () {
      if (!S.strokes.length) { error("Draw something first!"); return; }
      handIn({ drawing: { strokes: S.strokes } });
    });
  }

  function markTools() {
    Array.prototype.forEach.call($("palette").children, function (b, i) { b.setAttribute("aria-checked", i === S.colour); });
    Array.prototype.forEach.call($("sizes").children, function (b, i) { b.setAttribute("aria-checked", i === S.size); });
  }

  // ------------------------------------------------------------------ the end

  function renderReveal(room) {
    show("reveal");
    if (S.chains) return;
    S.chains = [];
    send("chains").then(function (data) {
      if (!data) return;
      S.chains = data.chains;
      var list = $("chain-list");
      list.innerHTML = "";
      data.chains.forEach(function (c) {
        var b = el("button", "chain-button" + (c.mine ? " mine" : ""));
        b.type = "button";
        b.appendChild(el("b", "", c.mine ? "Your chain" : c.owner + "'s chain"));
        b.appendChild(el("span", "", "“" + c.prompt + "”"));
        b.addEventListener("click", function () { openChain(c.index); });
        var li = el("li");
        li.appendChild(b);
        list.appendChild(li);
      });
      var mine = data.chains.filter(function (c) { return c.mine; })[0];
      openChain(mine ? mine.index : 0);
    });
  }

  function openChain(index) {
    send("chain", { index: index }).then(function (chain) {
      if (!chain) return;
      S.chain = chain;
      S.shown = 1;
      S.drawn = 0;
      Array.prototype.forEach.call($("chain-list").querySelectorAll(".chain-button"), function (b, i) {
        b.classList.toggle("current", i === index);
      });
      var mine = S.chains.filter(function (c) { return c.index === index && c.mine; }).length;
      $("chain-title").textContent = mine ? "Your chain" : chain.owner + "'s chain";
      $("chain-view").hidden = false;
      showEntries();
    });
  }

  function said(entry) {
    var who = entry.by;
    if (entry.kind === "prompt") return entry.auto ? who + " ran out of time, so the game picked" : who + " wrote";
    if (entry.kind === "draw") return entry.auto && !entry.strokes.length ? who + " ran out of time to draw" : who + " drew";
    return entry.auto && !entry.text ? who + " ran out of time to guess" : who + " guessed";
  }

  function showEntries() {
    var list = $("chain-entries");
    list.innerHTML = "";
    var entries = S.chain.entries;
    entries.slice(0, S.shown).forEach(function (e, i) {
      var li = el("li", e.kind + (i >= S.drawn && S.drawn ? " new" : ""));
      li.appendChild(el("p", "who", said(e)));
      if (e.kind === "draw") {
        var c = el("canvas");
        c.width = 800;
        c.height = 600;
        paint(c, e.strokes);
        li.appendChild(c);
      } else if (e.text) {
        li.appendChild(el("p", "words", e.text));
      }
      list.appendChild(li);
    });
    S.drawn = S.shown;
    var all = S.shown >= entries.length;
    $("btn-next").hidden = all;
    $("btn-all").hidden = all;
    $("btn-save").hidden = !all;
    if (list.lastChild && S.shown > 1) list.lastChild.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  // The whole chain as one tall picture, from the prompt to the last guess.
  function chainPicture(chain) {
    var W = 900, pad = 40, pic = W - 2 * pad, picH = pic * HEIGHT / WIDTH;
    var font = "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif";
    var measure = document.createElement("canvas").getContext("2d");
    function wrap(text, size) {
      measure.font = "700 " + size + "px " + font;
      var words = text.split(" "), lines = [], line = "";
      words.forEach(function (w) {
        var next = line ? line + " " + w : w;
        if (measure.measureText(next).width > pic && line) { lines.push(line); line = w; } else line = next;
      });
      if (line) lines.push(line);
      return lines;
    }
    var blocks = chain.entries.map(function (e) {
      var lines = e.kind === "draw" || !e.text ? [] : wrap(e.text, 34);
      return { e: e, lines: lines, h: 34 + (e.kind === "draw" ? picH + 20 : lines.length * 44 + 20) };
    });
    var H = 130 + blocks.reduce(function (n, b) { return n + b.h; }, 0) + 30;
    var canvas = document.createElement("canvas");
    canvas.width = W;
    canvas.height = H;
    var ctx = canvas.getContext("2d");
    ctx.fillStyle = "#f4f1ec";
    ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = "#334155";
    ctx.font = "800 40px " + font;
    ctx.fillText("Smoke Signals", pad, 64);
    ctx.fillStyle = "#64748b";
    ctx.font = "500 24px " + font;
    ctx.fillText(chain.owner + "'s chain", pad, 100);
    var y = 130;
    blocks.forEach(function (b) {
      ctx.fillStyle = "#64748b";
      ctx.font = "500 22px " + font;
      ctx.fillText(said(b.e), pad, y + 22);
      y += 34;
      if (b.e.kind === "draw") {
        ctx.fillStyle = "#ffffff";
        ctx.fillRect(pad, y, pic, picH);
        ctx.strokeStyle = "#d6d0c4";
        ctx.lineWidth = 2;
        ctx.strokeRect(pad, y, pic, picH);
        ctx.save();
        ctx.beginPath();
        ctx.rect(pad, y, pic, picH);
        ctx.clip();
        b.e.strokes.forEach(function (s) { line(ctx, s, pic / WIDTH, pad, y); });
        ctx.restore();
        y += picH + 20;
      } else {
        ctx.fillStyle = "#1f1b16";
        ctx.font = "700 34px " + font;
        b.lines.forEach(function (l) { ctx.fillText(l, pad, y + 34); y += 44; });
        y += 20;
      }
    });
    return canvas;
  }

  function savePicture() {
    var chain = S.chain;
    chainPicture(chain).toBlob(function (blob) {
      var name = "smoke-signals-" + chain.owner.replace(/[^A-Za-z0-9]+/g, "-").replace(/^-|-$/g, "").toLowerCase();
      KG.saveFile(name + ".png", blob).catch(function (e) { error(e.message); });
    }, "image/png");
  }

  // ------------------------------------------------------------------ leaving

  function leaveThen(next) {
    clearInterval(S.poll);
    stopTimer();
    KG.finish({}).catch(function () { return null; }).then(next);
  }

  function playAgain() {
    leaveThen(function () {
      S.task = null;
      S.chains = null;
      S.chain = null;
      $("chain-view").hidden = true;
      begin();
    });
  }

  // ------------------------------------------------------------------ start

  function begin() {
    return KG.start({ resume: true }).then(function (data) {
      render(data.public);
      startPolling();
    }, function (e) {
      error(e.message);
    });
  }

  function wire() {
    $("btn-join").addEventListener("click", function () {
      var code = $("join-code").value.trim();
      if (!code) { error("Type the game's code first."); return; }
      join(code);
    });
    $("join-code").addEventListener("keydown", function (e) { if (e.key === "Enter") $("btn-join").click(); });
    $("btn-create").addEventListener("click", function () {
      send("create", { speed: $("new-speed").value, rounds: parseInt($("new-rounds").value, 10), language: "en" })
        .then(function (view) { if (view) render(view); });
    });
    $("btn-begin").addEventListener("click", function () {
      send("begin").then(function (view) { if (view) render(view); });
    });
    $("btn-leave").addEventListener("click", function () {
      send("leave").then(function (view) { if (view) render(view); });
    });
    $("btn-prompt").addEventListener("click", function () { handInText("prompt-text"); });
    $("prompt-text").addEventListener("keydown", function (e) { if (e.key === "Enter") handInText("prompt-text"); });
    $("btn-more").addEventListener("click", function () {
      send("suggest").then(function (data) { if (data) showIdeas(data.suggestions); });
    });
    $("btn-guess").addEventListener("click", function () { handInText("guess-text"); });
    $("guess-text").addEventListener("keydown", function (e) { if (e.key === "Enter") handInText("guess-text"); });
    $("btn-skip").addEventListener("click", function () {
      send("skip").then(function (view) { if (view) render(view); });
    });
    twice($("btn-end"), "End it for everyone?", function () {
      send("end").then(function (view) { if (view) render(view); });
    });
    twice($("btn-quit"), "Leave? Your turns will be skipped.", function () {
      send("leave").then(function (view) { if (view) render(view); });
    });
    $("btn-next").addEventListener("click", function () { S.shown += 1; showEntries(); });
    $("btn-all").addEventListener("click", function () { S.shown = S.chain.entries.length; showEntries(); });
    $("btn-save").addEventListener("click", savePicture);
    $("btn-again").addEventListener("click", playAgain);
    $("btn-exit").addEventListener("click", function () { leaveThen(function () { KG.exit(); }); });
    setUpCanvas();
  }

  wire();
  KG.ready().then(function (info) {
    S.info = info;
    var settings = info.settings || {};
    if (settings.speed) $("new-speed").value = settings.speed;
    if (settings.rounds) $("new-rounds").value = String(settings.rounds);
    return begin();
  }).catch(function (e) {
    show("lobby");
    error(e.message);
  });
})();
