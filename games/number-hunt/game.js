/* Number Hunt: the server picks the secret number and answers each guess,
 * so this page never knows the answer and the score can't be faked. */
(function () {
  "use strict";
  var KG = window.KolibriGames;
  var $ = function (id) { return document.getElementById(id); };
  var S = { low: 1, high: 100, min: 1, max: 100, guesses: [], busy: false, over: false };

  function show(id) {
    ["intro", "play", "done"].forEach(function (s) { $(s).hidden = s !== id; });
  }

  function clock(sec) {
    sec = Math.round(sec || 0);
    return Math.floor(sec / 60) + ":" + (sec % 60 < 10 ? "0" : "") + (sec % 60);
  }

  function pct(n) {
    return ((n - S.min) / Math.max(1, S.max - S.min)) * 100;
  }

  function drawLine() {
    var line = $("line");
    Array.prototype.slice.call(line.querySelectorAll(".mark")).forEach(function (m) { m.remove(); });
    $("window").style.left = pct(S.low) + "%";
    $("window").style.right = (100 - pct(S.high)) + "%";
    S.guesses.forEach(function (g) {
      var m = document.createElement("span");
      m.className = "mark " + g.hint;
      m.textContent = g.value;
      m.style.left = Math.min(96, Math.max(4, pct(g.value))) + "%";
      line.appendChild(m);
    });
    $("end-low").textContent = S.min;
    $("end-high").textContent = S.max;
  }

  function addGuess(value, hint) {
    S.guesses.push({ value: value, hint: hint });
    if (hint === "higher") S.low = Math.max(S.low, value + 1);
    if (hint === "lower") S.high = Math.min(S.high, value - 1);
    var li = document.createElement("li");
    li.className = hint;
    li.textContent = value + (hint === "higher" ? ": go higher" : hint === "lower" ? ": go lower" : ": found it");
    $("history").appendChild(li);
    drawLine();
  }

  function prompt(text) { $("prompt").textContent = text; }

  function error(where, text) {
    var e = $(where + "-error");
    e.textContent = text || "";
    e.hidden = !text;
  }

  function begin(resume) {
    error("intro", "");
    $("btn-start").disabled = true;
    KG.start({ resume: resume }).then(function (res) {
      var pub = res.public || {};
      S.min = S.low = pub.low || 1;
      S.max = S.high = pub.high || 100;
      S.guesses = [];
      S.over = false;
      $("history").innerHTML = "";
      (pub.guesses || []).forEach(function (g) { addGuess(g.value, g.hint); });
      drawLine();
      show("play");
      prompt(S.guesses.length ? "Welcome back. Keep going." : "Make your first guess.");
      $("guess").min = S.min;
      $("guess").max = S.max;
      $("guess").value = "";
      $("guess").focus();
      if (pub.found) finish();
    }).catch(function (e) {
      error("intro", e.message);
    }).then(function () { $("btn-start").disabled = false; });
  }

  $("btn-start").addEventListener("click", function () { begin(true); });
  $("btn-again").addEventListener("click", function () { show("intro"); begin(false); });
  $("btn-exit").addEventListener("click", function () { KG.exit(); });

  $("guess-form").addEventListener("submit", function (e) {
    e.preventDefault();
    if (S.busy || S.over) return;
    var value = parseInt($("guess").value, 10);
    if (isNaN(value) || value < S.min || value > S.max) {
      error("play", "Guess a whole number from " + S.min + " to " + S.max + ".");
      return;
    }
    error("play", "");
    S.busy = true;
    $("btn-guess").disabled = true;
    KG.event("guess", { value: value }).then(function (reply) {
      addGuess(value, reply.hint);
      if (reply.hint === "correct") return finish();
      prompt(value + " is too " + (reply.hint === "higher" ? "low" : "high") + ". My number is " + reply.hint + ".");
      $("guess").value = "";
      $("guess").focus();
    }).catch(function (err) {
      error("play", err.message);
    }).then(function () {
      S.busy = false;
      $("btn-guess").disabled = false;
    });
  });

  function finish() {
    S.over = true;
    prompt("Found it!");
    return KG.finish({}).then(function (res) {
      var a = res.attempt;
      $("done-title").textContent = "You found it!";
      $("done-summary").textContent = "The number was " + S.guesses[S.guesses.length - 1].value + ". You took " +
        a.score + (a.score === 1 ? " guess" : " guesses") + " in " + clock(a.seconds) + ".";
      var standing = res.standing;
      var note = a.practice ? "This was practice: your first attempt is the one that counts. " : "";
      if (standing) note += "You're number " + standing.rank + " of " + standing.of + " on the scoreboard.";
      $("done-standing").textContent = note;
      show("done");
      return KG.scoreboard().then(drawBoard);
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
    rows.slice(0, 8).forEach(function (r) {
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

  KG.on("timeup", function () {
    S.over = true;
    $("done-title").textContent = "Time's up";
    $("done-summary").textContent = "You ran out of time on this attempt.";
    $("done-standing").textContent = "";
    $("board").hidden = true;
    show("done");
  });

  KG.ready().then(function (info) {
    var high = (info.settings && info.settings.max) || 100;
    $("intro-high").textContent = high;
    if (info.preview) {
      $("intro-rule").textContent = "Number Hunt needs Kolibri Games to play, because the secret number is kept on the server.";
      $("btn-start").disabled = true;
      return;
    }
    var counts = info.rules && info.rules.counts;
    var limit = info.rules && info.rules.time_limit;
    var bits = [];
    if (counts === "first") bits.push(info.summary && info.summary.first_used
      ? "You've already played your counted attempt, so this one is practice."
      : "Your first attempt is the one that counts on the scoreboard.");
    if (limit) bits.push("You have " + Math.round(limit / 60) + " minutes.");
    bits.push("A perfect strategy needs at most " + Math.ceil(Math.log2(high + 1)) + " guesses.");
    $("intro-rule").textContent = bits.join(" ");
  }).catch(function (err) { error("intro", err.message); });
})();
