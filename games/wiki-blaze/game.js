/* Wiki BLAZE (Browsing Links A-to-Z Exploration).
 *
 * The Kolibri Games server does the real work: it reads the articles from the
 * device's Wikipedia file, checks every link, keeps the learner's chain of
 * articles and works out the score. This page only shows what the server
 * sends and passes on what the learner clicks:
 *
 *   KolibriGames.move("go",   {to: path})   follow a link in the article
 *   KolibriGames.move("back", {step: n})    go back to article n of the chain
 *
 * Each reply has the new page, the chain and whether the goal is reached.
 */
(function () {
  "use strict";
  var KG = window.KolibriGames;
  var $ = function (id) { return document.getElementById(id); };
  var S = { busy: false, started: 0, timer: null, goal: null, steps: 0, info: null };

  // ------------------------------------------------------------------ helpers

  function show(id) {
    ["intro", "play", "done"].forEach(function (s) { $(s).hidden = s !== id; });
    $("hud").hidden = id !== "play";
  }

  function clock(sec) {
    sec = Math.max(0, Math.round(sec || 0));
    return Math.floor(sec / 60) + ":" + (sec % 60 < 10 ? "0" : "") + (sec % 60);
  }

  function links(n) { return n + (n === 1 ? " link" : " links"); }

  function error(where, text) {
    var e = $(where + "-error");
    e.textContent = text || "";
    e.hidden = !text;
  }

  function startClock(elapsed) {
    S.started = Date.now() - (elapsed || 0) * 1000;
    clearInterval(S.timer);
    var tick = function () { $("hud-clock").textContent = clock((Date.now() - S.started) / 1000); };
    tick();
    S.timer = setInterval(tick, 1000);
  }

  // ------------------------------------------------------------------ drawing

  // The chain of articles from the start to here. Earlier articles are buttons
  // that go back to them.
  function drawChain(chain) {
    var list = $("chain");
    list.innerHTML = "";
    chain.forEach(function (item, i) {
      var li = document.createElement("li");
      if (i === chain.length - 1) {
        var here = document.createElement("span");
        here.className = "here";
        here.textContent = item.title;
        here.setAttribute("aria-current", "page");
        li.appendChild(here);
      } else {
        var b = document.createElement("button");
        b.type = "button";
        b.textContent = item.title;
        b.title = "Go back to " + item.title + " (doesn't count against you)";
        b.addEventListener("click", function () { send("back", { step: i }); });
        li.appendChild(b);
      }
      list.appendChild(li);
    });
    list.scrollLeft = list.scrollWidth;
  }

  // The article itself. The server has already removed scripts and turned
  // every usable link into <a data-to="...">.
  function drawPage(page) {
    var box = $("page");
    box.innerHTML = page.html;
    if (!box.querySelector("h1")) {
      var h = document.createElement("h1");
      h.textContent = page.title;
      box.insertBefore(h, box.firstChild);
    }
    Array.prototype.forEach.call(box.querySelectorAll("a[data-to]"), function (a) {
      a.setAttribute("href", "#");
      if (a.getAttribute("data-to") === S.goal) {
        a.classList.add("goal-link");
        a.title = "This is the goal!";
      }
    });
    window.scrollTo(0, 0);
  }

  function draw(reply) {
    S.steps = reply.steps;
    $("hud-links").textContent = links(reply.steps);
    drawChain(reply.chain);
    drawPage(reply.page);
  }

  // ------------------------------------------------------------------ playing

  function begin() {
    error("intro", "");
    $("btn-start").disabled = true;
    KG.start({ resume: true }).then(function (res) {
      var p = res.public;
      S.goal = p.goal.path;
      $("hud-start").textContent = p.start.title;
      $("hud-goal").textContent = p.goal.title;
      show("play");
      startClock(res.elapsed);
      draw(p);
      if (p.done) finish();
    }).catch(function (e) {
      error("intro", e.message);
    }).then(function () { $("btn-start").disabled = false; });
  }

  function send(kind, data) {
    if (S.busy) return;
    S.busy = true;
    error("play", "");
    document.body.classList.add("busy");
    KG.move(kind, data).then(function (reply) {
      draw(reply);
      if (reply.done) finish();
    }).catch(function (e) {
      error("play", e.message);
    }).then(function () {
      S.busy = false;
      document.body.classList.remove("busy");
    });
  }

  // Clicking (or pressing Enter on) a link in the article.
  $("page").addEventListener("click", function (e) {
    var a = e.target.closest ? e.target.closest("a") : null;
    if (!a) return;
    e.preventDefault();
    if (a.hasAttribute("data-to")) send("go", { to: a.getAttribute("data-to") });
  });

  function finish() {
    clearInterval(S.timer);
    return KG.finish({}).then(function (res) {
      var a = res.attempt, d = a.detail || {};
      $("done-title").textContent = "You made it!";
      $("done-summary").textContent = "From " + d.start + " to " + d.goal + " in " + links(a.score) +
        " and " + clock(a.seconds) + ". You visited " + d.pages_visited + (d.pages_visited === 1 ? " page." : " pages.");
      var route = $("done-route");
      route.innerHTML = "";
      (d.route || []).forEach(function (t) {
        var li = document.createElement("li");
        li.textContent = t;
        route.appendChild(li);
      });
      var note = a.practice ? "This was practice: your first attempt is the one that counts. " : "";
      if (res.standing) note += "You're number " + res.standing.rank + " of " + res.standing.of + " on the scoreboard.";
      $("done-standing").textContent = note;
      show("done");
      if (S.info && S.info.challenge) return KG.scoreboard().then(drawBoard);
      $("board").hidden = true;
    }).catch(function (err) {
      $("done-title").textContent = "Couldn't save your result";
      $("done-summary").textContent = err.message;
      show("done");
    });
  }

  function drawBoard(data) {
    var rows = (data && data.rows) || [];
    var body = $("board").querySelector("tbody");
    body.innerHTML = "";
    rows.slice(0, 10).forEach(function (r) {
      var tr = document.createElement("tr");
      if (r.me) tr.className = "me";
      [r.rank, r.name + (r.me ? " (you)" : ""), r.score, clock(r.seconds)].forEach(function (v, i) {
        var td = document.createElement("td");
        td.textContent = v;
        if (i >= 2) td.className = "num";
        tr.appendChild(td);
      });
      body.appendChild(tr);
    });
    $("board").hidden = rows.length === 0;
  }

  $("btn-start").addEventListener("click", begin);
  $("btn-again").addEventListener("click", function () { show("intro"); begin(); });
  $("btn-exit").addEventListener("click", function () { KG.exit(); });

  KG.on("timeup", function () {
    clearInterval(S.timer);
    $("done-title").textContent = "Time's up";
    $("done-summary").textContent = "You ran out of time before reaching the goal.";
    $("done-route").innerHTML = "";
    $("done-standing").textContent = "";
    $("board").hidden = true;
    show("done");
  });

  // ------------------------------------------------------------------ start up

  KG.ready().then(function (info) {
    S.info = info;
    if (info.preview) {
      $("intro-rule").textContent = "Wiki BLAZE needs Kolibri Games to play, because the server reads Wikipedia and checks every link.";
      $("btn-start").disabled = true;
      return;
    }
    var c = info.challenge;
    if (c && c.start) {
      $("intro-start").textContent = c.start;
      $("intro-goal").textContent = c.goal;
      $("intro-pair").hidden = false;
    }
    var bits = [];
    if (c) bits.push("Challenge: " + c.title + ".");
    else bits.push(info.settings && info.settings.start ? "" : "Your start and goal are picked at random each time.");
    if (c && info.rules.counts === "first") bits.push(info.summary && info.summary.first_used
      ? "You've already played your counted attempt, so this one is practice."
      : "Your first attempt is the one that counts.");
    if (info.rules.time_limit) bits.push("You have " + Math.round(info.rules.time_limit / 60) + " minutes.");
    $("intro-rule").textContent = bits.join(" ").trim();
  }).catch(function (err) { error("intro", err.message); });
})();
